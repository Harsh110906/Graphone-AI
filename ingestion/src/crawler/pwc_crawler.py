"""
Papers with Code (PwC) Crawler & GitHub Metrics Extractor.

IMPORTANT DATA INTEGRITY RULES:
- `authors` must ONLY contain real human author names, or [] if unresolvable.
- NEVER substitutes GitHub organization or repository owner names as authors.
- `github_stars` is fetched live via GitHubClient (never estimated).
- Real verifiable paper URLs (arXiv or PwC canonical URLs).

Sources:
- Papers with Code Latest Trending Feed (https://paperswithcode.com/latest)
- Hugging Face Daily Papers Feed (https://huggingface.co/api/daily_papers)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional
from bs4 import BeautifulSoup
import httpx
import structlog

from src.crawler.base import BaseCrawler, RawDocument
from src.crawler.github_client import GitHubClient
from src.crawler.rate_limiter import DomainRateLimiter
from src.schemas.research_paper import ResearchPaper, ResearchPaperContent
from src.schemas.startup import Source

logger = structlog.get_logger(__name__)

PWC_LATEST_URL = "https://paperswithcode.com/latest"
HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"


class PwcCrawler(BaseCrawler):
    """
    Crawler connecting research papers (arXiv) with official GitHub repositories and star metrics.
    """

    def __init__(
        self,
        github_client: Optional[GitHubClient] = None,
        max_results: int = 50,
        rate_limiter: Optional[DomainRateLimiter] = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=0.5,
            max_concurrent=1,
            burst=1,
        )
        super().__init__(
            source_name="papers_with_code",
            rate_limiter=limiter,
            max_retries=3,
            timeout_seconds=30,
            concurrency=1,
        )
        self.github_client = github_client or GitHubClient()
        self.max_results = max_results
        self._http_client: Optional[httpx.AsyncClient] = None

    async def discover(self) -> AsyncIterator[str]:
        """Yield PwC and HF Daily Papers endpoints."""
        yield PWC_LATEST_URL
        yield HF_DAILY_PAPERS_URL

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Parse raw HTML / JSON into validated ResearchPaper records."""
        url = doc.source_url

        if "huggingface.co" in url:
            return await self._parse_hf_json(doc)
        elif "paperswithcode.com" in url:
            return await self._parse_pwc_html(doc)

        return []

    async def _parse_pwc_html(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Parse Papers with Code HTML card listings."""
        soup = BeautifulSoup(doc.raw_content, "lxml")
        articles = soup.find_all("div", class_=re.compile(r"paper-card|infinite-item|item"))
        if not articles:
            articles = soup.find_all("article")

        records = []

        for art in articles[:self.max_results]:
            # Title
            h = art.find(["h2", "h3"])
            title = h.text.strip() if h else None
            if not title:
                continue

            # Links
            arxiv_url = None
            github_url = None
            pwc_url = None

            for a in art.find_all("a", href=True):
                href = a["href"].strip()
                if "arxiv.org/abs/" in href:
                    arxiv_url = href
                elif "github.com/" in href and not any(x in href.lower() for x in ["paperswithcode", "login", "signup"]):
                    github_url = href
                elif href.startswith("/papers/"):
                    pwc_url = f"https://paperswithcode.com{href}"

            paper_url = arxiv_url or pwc_url
            if not paper_url:
                continue

            # Extract real human authors from arXiv if arXiv URL is present
            authors: list[str] = []
            if arxiv_url:
                arxiv_id_match = re.search(r"arxiv\.org/abs/([0-9]+\.[0-9]+(?:v[0-9]+)?)", arxiv_url)
                if arxiv_id_match:
                    arxiv_id = arxiv_id_match.group(1)
                    authors = await self._fetch_arxiv_authors(arxiv_id)

            # GitHub Stars live query
            github_stars = None
            if github_url:
                try:
                    github_stars = await self.github_client.get_stars_from_url(github_url)
                except Exception as e:
                    logger.warning("pwc_github_stars_fetch_failed", url=github_url, error=str(e))
                    github_stars = None

            # Build record
            rec = self._build_paper_record(
                title=title,
                authors=authors,  # Human author list or [] — never an organization name
                paper_url=paper_url,
                github_url=github_url,
                github_stars=github_stars,
                source_name="Papers with Code",
            )
            if rec:
                records.append(rec)

        logger.info("pwc_papers_parsed", total=len(records))
        return records

    async def _parse_hf_json(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Parse Hugging Face Daily Papers API JSON."""
        import json
        try:
            data = json.loads(doc.raw_content)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        records = []
        for item in data[:self.max_results]:
            paper_obj = item.get("paper", {})
            title = paper_obj.get("title") or item.get("title")
            if not title:
                continue

            arxiv_id = paper_obj.get("id")
            paper_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None
            if not paper_url:
                continue

            # Extract real human author names from HF API payload
            raw_authors = paper_obj.get("authors", [])
            authors = []
            for a in raw_authors:
                if isinstance(a, dict) and a.get("name"):
                    authors.append(a["name"].strip())
                elif isinstance(a, str) and a.strip():
                    authors.append(a.strip())

            pub_date = paper_obj.get("publishedAt") or item.get("publishedAt")

            # Extract GitHub repo from summary or AI keywords if present
            summary = paper_obj.get("summary", "")
            gh_match = re.search(r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", summary)
            github_url = gh_match.group(0) if gh_match else None
            github_stars = None

            if github_url:
                github_stars = await self.github_client.get_stars_from_url(github_url)

            rec = self._build_paper_record(
                title=title,
                authors=authors,  # Real human authors
                paper_url=paper_url,
                github_url=github_url,
                github_stars=github_stars,
                published_date=pub_date,
                source_name="HF Daily Papers (PwC Archive)",
            )
            if rec:
                records.append(rec)

        logger.info("hf_daily_papers_parsed", total=len(records))
        return records

    async def _fetch_arxiv_authors(self, arxiv_id: str) -> list[str]:
        """Fetch canonical human authors list from arXiv Atom API."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)

        api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        try:
            res = await self._http_client.get(api_url, headers={"User-Agent": "GraphOneResearchBot/1.0"})
            if res.status_code == 200:
                root = ET.fromstring(res.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                authors = [
                    a.find("atom:name", ns).text.strip()
                    for a in root.findall("atom:entry/atom:author", ns)
                    if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
                ]
                return authors
        except Exception as e:
            logger.warning("arxiv_author_fetch_failed", arxiv_id=arxiv_id, error=str(e))

        return []  # Rule 0: Empty list if unresolvable — NEVER organization name

    def _build_paper_record(
        self,
        title: str,
        authors: list[str],
        paper_url: str,
        github_url: Optional[str] = None,
        github_stars: Optional[int] = None,
        published_date: Optional[str] = None,
        source_name: str = "Papers with Code",
    ) -> Optional[dict[str, Any]]:
        """Validate and construct a schema-compliant ResearchPaper record."""
        collected_at = datetime.now(timezone.utc)

        if published_date:
            try:
                dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
            except Exception:
                dt = collected_at
        else:
            dt = collected_at

        record = {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": title,
                "authors": authors,
                "paper_url": paper_url,
                "github_url": github_url,
                "github_stars": github_stars,
                "published_date": dt.isoformat(),
            },
            "collectedAt": collected_at.isoformat(),
        }

        # Pydantic validation
        try:
            ResearchPaper(
                schemaVersion="1.0",
                recordType="RESEARCH_PAPER",
                content=ResearchPaperContent(
                    title=title,
                    authors=authors,
                    paper_url=paper_url,
                    github_url=github_url,
                    github_stars=github_stars,
                    published_date=dt,
                ),
                collectedAt=collected_at,
            )
            return record
        except Exception as e:
            logger.error("pwc_paper_schema_validation_failed", title=title, error=str(e))
            return None
