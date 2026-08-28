"""
GitHub API client — rate-limit aware with caching.

Fetches live star counts for repositories. Never guesses this number.
Caches results with a configurable TTL (default: 24 hours).
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"


class GitHubRateLimitError(Exception):
    """Raised when GitHub API rate limit is exhausted."""

    def __init__(self, reset_at: float):
        self.reset_at = reset_at
        super().__init__(f"GitHub rate limit exhausted. Resets at {reset_at}")


class GitHubClient:
    """
    Async GitHub API client with rate-limit awareness and caching.

    - Authenticated requests: 5,000/hour
    - Unauthenticated: 60/hour
    - Star counts are cached with TTL to avoid redundant API calls
    """

    def __init__(self, token: str | None = None, cache_ttl: int | None = None):
        self._token = token or settings.github_token
        self._cache_ttl = cache_ttl or settings.github_stars_cache_ttl_seconds
        self._cache: dict[str, tuple[int, float]] = {}  # repo -> (stars, cached_at)
        self._remaining: int = 5000 if self._token else 60
        self._reset_at: float = 0.0
        self._client: httpx.AsyncClient | None = None

    @property
    def remaining(self) -> int:
        """Return remaining GitHub API requests in current window."""
        return self._remaining

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": settings.crawler_user_agent,
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=headers,
                timeout=httpx.Timeout(15.0),
                follow_redirects=True,
            )
        return self._client

    def _update_rate_limits(self, headers: httpx.Headers) -> None:
        """Update rate limit tracking from response headers."""
        remaining = headers.get("x-ratelimit-remaining")
        reset = headers.get("x-ratelimit-reset")
        if remaining is not None:
            self._remaining = int(remaining)
        if reset is not None:
            self._reset_at = float(reset)

        if self._remaining <= 5:
            logger.warning(
                "github_rate_limit_low",
                remaining=self._remaining,
                reset_at=self._reset_at,
            )

    async def get_repo_stars(self, owner: str, repo: str) -> Optional[int]:
        """
        Get the star count for a GitHub repository.

        Returns the live count from the API, cached for cache_ttl seconds.
        Returns None if the repo doesn't exist or API is unavailable.
        Never invents a number.
        """
        cache_key = f"{owner}/{repo}".lower()

        # Check cache
        if cache_key in self._cache:
            stars, cached_at = self._cache[cache_key]
            if time.time() - cached_at < self._cache_ttl:
                logger.debug("github_stars_cache_hit", repo=cache_key, stars=stars)
                return stars

        # Check rate limit before making request
        if self._remaining <= 1 and time.time() < self._reset_at:
            wait_time = self._reset_at - time.time() + 1
            logger.warning(
                "github_rate_limit_wait",
                repo=cache_key,
                wait_seconds=round(wait_time, 1),
            )
            # If we'd have to wait more than 5 minutes, return None instead of blocking
            if wait_time > 300:
                logger.warning("github_rate_limit_skip", repo=cache_key)
                return None
            await asyncio.sleep(wait_time)

        try:
            client = await self._get_client()
            response = await client.get(f"/repos/{owner}/{repo}")
            self._update_rate_limits(response.headers)

            if response.status_code == 404:
                logger.info("github_repo_not_found", repo=cache_key)
                return None

            if response.status_code == 403:
                # Rate limited
                self._update_rate_limits(response.headers)
                raise GitHubRateLimitError(self._reset_at)

            response.raise_for_status()
            data = response.json()
            stars = data.get("stargazers_count")

            if stars is not None:
                self._cache[cache_key] = (stars, time.time())
                logger.info("github_stars_fetched", repo=cache_key, stars=stars)

            return stars

        except GitHubRateLimitError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                "github_api_error",
                repo=cache_key,
                status=e.response.status_code,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.error(
                "github_unexpected_error",
                repo=cache_key,
                error_type=type(e).__name__,
                error=str(e),
            )
            return None

    @staticmethod
    def parse_github_url(url: str) -> tuple[str, str] | None:
        """
        Extract owner/repo from a GitHub URL.

        Handles:
        - https://github.com/owner/repo
        - https://github.com/owner/repo/tree/main
        - https://github.com/owner/repo.git

        Returns (owner, repo) tuple or None if not a valid GitHub repo URL.
        """
        import re
        pattern = r"github\.com/([^/]+)/([^/\s#?.]+)"
        match = re.search(pattern, url)
        if match:
            owner = match.group(1)
            repo = match.group(2).rstrip(".git")
            # Filter out non-repo paths
            if owner.lower() in ("topics", "explore", "settings", "notifications"):
                return None
            return (owner, repo)
        return None

    async def get_stars_from_url(self, github_url: str) -> Optional[int]:
        """Get star count from a GitHub URL string."""
        parsed = self.parse_github_url(github_url)
        if parsed is None:
            logger.debug("github_url_not_parseable", url=github_url)
            return None
        owner, repo = parsed
        return await self.get_repo_stars(owner, repo)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
