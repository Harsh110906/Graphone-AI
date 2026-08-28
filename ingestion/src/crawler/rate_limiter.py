"""
Per-domain async rate limiter.

Ensures we never exceed a target request rate for any given domain.
Uses asyncio semaphores + token-bucket with per-domain tracking.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


class DomainRateLimiter:
    """
    Token-bucket rate limiter keyed by domain.

    Args:
        requests_per_second: Max requests per second per domain.
        max_concurrent: Max concurrent requests per domain.
        burst: Max burst size (tokens that can accumulate).
    """

    def __init__(
        self,
        requests_per_second: float = 1.0,
        max_concurrent: int = 2,
        burst: int = 3,
    ):
        self._rps = requests_per_second
        self._max_concurrent = max_concurrent
        self._burst = burst
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._max_concurrent)
        )
        self._last_request: dict[str, float] = {}
        self._tokens: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL for rate-limiting purposes."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.hostname or url

    async def acquire(self, url: str) -> None:
        """
        Wait until a request to the given URL's domain is permitted.

        Implements token-bucket algorithm with per-domain semaphore.
        """
        domain = self._extract_domain(url)
        semaphore = self._semaphores[domain]

        # Wait for concurrency slot
        await semaphore.acquire()

        async with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            tokens = self._tokens.get(domain, self._burst)

            # Refill tokens based on elapsed time
            elapsed = now - last
            tokens = min(self._burst, tokens + elapsed * self._rps)

            if tokens < 1.0:
                # Need to wait for a token
                wait_time = (1.0 - tokens) / self._rps
                logger.debug(
                    "rate_limit_wait",
                    domain=domain,
                    wait_seconds=round(wait_time, 3),
                )
                await asyncio.sleep(wait_time)
                tokens = 1.0

            # Consume a token
            self._tokens[domain] = tokens - 1.0
            self._last_request[domain] = time.monotonic()

    def release(self, url: str) -> None:
        """Release the concurrency slot for a domain."""
        domain = self._extract_domain(url)
        semaphore = self._semaphores[domain]
        semaphore.release()

    async def __aenter__(self) -> "DomainRateLimiter":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class RateLimitedSession:
    """
    Context manager that wraps a URL with rate limiting.

    Usage:
        async with rate_limiter.session(url) as _:
            response = await client.get(url)
    """

    def __init__(self, limiter: DomainRateLimiter, url: str):
        self._limiter = limiter
        self._url = url

    async def __aenter__(self) -> str:
        await self._limiter.acquire(self._url)
        return self._url

    async def __aexit__(self, *args: object) -> None:
        self._limiter.release(self._url)
