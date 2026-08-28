"""
arXiv official API crawler.

Uses the arXiv API (http://export.arxiv.org/api/query) to fetch research papers.
This is the primary proof-of-life crawler for Phase 1.

arXiv API rate limit: ~3 requests per second (we limit to 1/s to be safe).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, AsyncIterator
from xml.etree import ElementTree as ET

import structlog

from src.crawler.base import BaseCrawler, RawDocument
from src.crawler.github_client import GitHubClient
from src.crawler.rate_limiter import DomainRateLimiter

logger = structlog.get_logger(__name__)

# arXiv API endpoint
ARXIV_API_URL = "http://export.arxiv.org/api/query"

# Atom/arXiv namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivCrawler(BaseCrawler):
    """
    Crawler for arXiv research papers via the official API.

    Fetches papers matching a search query, extracts structured metadata,
    and enriches with GitHub star counts when a repo link is present.
    """

    def __init__(
        self,
        search_query: str = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.RO OR cat:cs.NE OR cat:stat.ML",
        max_results: int = 100,
        github_client: GitHubClient | None = None,
        rate_limiter: DomainRateLimiter | None = None,
    ):
        # arXiv asks for max 3 req/s — we use 1/s for safety
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=1.0,
            max_concurrent=1,
            burst=1,
        )
        super().__init__(
            source_name="arxiv",
            rate_limiter=limiter,
            max_retries=3,
            timeout_seconds=30,
            concurrency=1,
        )
        self.search_query = search_query
        self.max_results = max_results
        self.github_client = github_client or GitHubClient()

    async def discover(self) -> AsyncIterator[str]:
        """
        Generate arXiv API query URLs with pagination.

        arXiv API supports start + max_results pagination.
        Each URL returns up to 100 results in Atom XML.
        """
        batch_size = min(100, self.max_results)
        fetched = 0
        start = 0

        while fetched < self.max_results:
            count = min(batch_size, self.max_results - fetched)
            url = (
                f"{ARXIV_API_URL}?"
                f"search_query={self.search_query}"
                f"&start={start}"
                f"&max_results={count}"
                f"&sortBy=submittedDate"
                f"&sortOrder=descending"
            )
            yield url
            start += count
            fetched += count

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """
        Parse arXiv Atom XML response into ResearchPaper records.

        Every field comes directly from the API response.
        github_stars comes from the GitHub API — never invented.
        Missing fields are null.
        """
        records: list[dict[str, Any]] = []

        try:
            root = ET.fromstring(doc.raw_content)
        except ET.ParseError as e:
            logger.error(
                "arxiv_xml_parse_error",
                url=doc.source_url,
                error=str(e),
            )
            return records

        entries = root.findall("atom:entry", NS)
        logger.info("arxiv_entries_found", count=len(entries), url=doc.source_url)

        for entry in entries:
            try:
                record = await self._parse_entry(entry)
                if record:
                    records.append(record)
            except Exception as e:
                title_el = entry.find("atom:title", NS)
                title = title_el.text.strip() if title_el is not None and title_el.text else "unknown"
                logger.error(
                    "arxiv_entry_parse_error",
                    title=title,
                    error_type=type(e).__name__,
                    error=str(e),
                )

        return records

    async def _parse_entry(self, entry: ET.Element) -> dict[str, Any] | None:
        """Parse a single arXiv entry element into a record dict."""
        # Extract title
        title_el = entry.find("atom:title", NS)
        if title_el is None or not title_el.text:
            return None
        title = re.sub(r"\s+", " ", title_el.text.strip())

        # Extract authors
        author_els = entry.findall("atom:author/atom:name", NS)
        authors = [a.text.strip() for a in author_els if a.text]

        # Extract arXiv ID and construct paper URL
        id_el = entry.find("atom:id", NS)
        if id_el is None or not id_el.text:
            return None
        arxiv_url = id_el.text.strip()
        # Extract arxiv ID from URL: http://arxiv.org/abs/2301.12345v1 -> 2301.12345
        arxiv_id_match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", arxiv_url)
        arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else arxiv_url

        # Extract published date
        published_el = entry.find("atom:published", NS)
        if published_el is None or not published_el.text:
            return None
        published_date = published_el.text.strip()

        # Look for GitHub links in the abstract/summary
        summary_el = entry.find("atom:summary", NS)
        summary_text = summary_el.text.strip() if summary_el is not None and summary_el.text else ""

        # Also check arxiv:comment for GitHub links
        comment_el = entry.find("arxiv:comment", NS)
        comment_text = comment_el.text.strip() if comment_el is not None and comment_el.text else ""

        # Check all links for GitHub repo
        github_url = None
        link_els = entry.findall("atom:link", NS)
        for link in link_els:
            href = link.get("href", "")
            if "github.com" in href:
                github_url = href
                break

        # Also search summary and comment for GitHub URLs
        if not github_url:
            github_pattern = r"https?://github\.com/[^\s)>\]\"']+"
            for text in [summary_text, comment_text]:
                match = re.search(github_pattern, text)
                if match:
                    github_url = match.group(0).rstrip(".,;:")
                    break

        # Fetch GitHub stars if we have a repo URL
        github_stars = None
        if github_url:
            try:
                github_stars = await self.github_client.get_stars_from_url(github_url)
            except Exception as e:
                logger.warning(
                    "github_stars_fetch_failed",
                    github_url=github_url,
                    paper_title=title[:80],
                    error=str(e),
                )

        record = {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": title,
                "authors": authors,
                "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
                "github_url": github_url,
                "github_stars": github_stars,
                "published_date": published_date,
            },
            "collectedAt": datetime.utcnow().isoformat(),
            # Metadata for lineage tracking (not part of the schema, used internally)
            "_metadata": {
                "arxiv_id": arxiv_id,
                "source_name": "arxiv",
                "extraction_method": "api_structured",
            },
        }

        logger.debug(
            "arxiv_paper_parsed",
            title=title[:80],
            arxiv_id=arxiv_id,
            has_github=github_url is not None,
            github_stars=github_stars,
        )

        return record

    async def close(self) -> None:
        await super().close()
        await self.github_client.close()
