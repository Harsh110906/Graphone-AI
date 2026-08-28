"""
Incremental crawling engine for freshness-critical signal monitoring.

Stores and tracks `last_seen_hash` (SHA-256 of document content) and `last_crawled_at` timestamp.
Skips unchanged content on subsequent crawl cycles to save bandwidth, compute, and avoid redundant downstream extraction.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import structlog

logger = structlog.get_logger(__name__)


class CrawlStateEntry:
    """Represents the crawl state of a single URL."""

    def __init__(
        self,
        url: str,
        last_seen_hash: str,
        last_crawled_at: float,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ):
        self.url = url
        self.last_seen_hash = last_seen_hash
        self.last_crawled_at = last_crawled_at
        self.etag = etag
        self.last_modified = last_modified

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "last_seen_hash": self.last_seen_hash,
            "last_crawled_at": self.last_crawled_at,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrawlStateEntry:
        return cls(
            url=data["url"],
            last_seen_hash=data["last_seen_hash"],
            last_crawled_at=data["last_crawled_at"],
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
        )


class IncrementalCrawlTracker:
    """
    Manages URL content hashes and crawl timestamps.
    Provides persistence to disk and fast in-memory lookup.
    """

    def __init__(self, state_file_path: Optional[str | Path] = None):
        self.state_file_path = Path(state_file_path) if state_file_path else None
        self._state: Dict[str, CrawlStateEntry] = {}
        if self.state_file_path and self.state_file_path.exists():
            self.load()

    @staticmethod
    def compute_content_hash(content: str | bytes) -> str:
        """Compute SHA-256 hash of document body."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def has_content_changed(self, url: str, current_content: str | bytes) -> bool:
        """
        Check if the content for a URL has changed since it was last crawled.
        Returns True if URL is new or content hash differs.
        """
        current_hash = self.compute_content_hash(current_content)
        entry = self._state.get(url)

        if not entry:
            return True

        return entry.last_seen_hash != current_hash

    def should_fetch_url(self, url: str, min_interval_seconds: float = 300.0) -> bool:
        """
        Check if a URL should be crawled based on elapsed time.
        If crawled within `min_interval_seconds`, skip network request unless forced.
        """
        entry = self._state.get(url)
        if not entry:
            return True

        elapsed = time.time() - entry.last_crawled_at
        return elapsed >= min_interval_seconds

    def update_crawl_state(
        self,
        url: str,
        content: str | bytes,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> bool:
        """
        Record a completed crawl.
        Returns True if this was a new or changed document, False if unchanged.
        """
        current_hash = self.compute_content_hash(content)
        entry = self._state.get(url)
        is_changed = True

        if entry:
            is_changed = (entry.last_seen_hash != current_hash)
            entry.last_seen_hash = current_hash
            entry.last_crawled_at = time.time()
            if etag:
                entry.etag = etag
            if last_modified:
                entry.last_modified = last_modified
        else:
            self._state[url] = CrawlStateEntry(
                url=url,
                last_seen_hash=current_hash,
                last_crawled_at=time.time(),
                etag=etag,
                last_modified=last_modified,
            )

        if is_changed:
            logger.debug("incremental_crawl_content_changed", url=url, content_hash=current_hash)
        else:
            logger.debug("incremental_crawl_content_unchanged", url=url)

        return is_changed

    def get_state(self, url: str) -> Optional[CrawlStateEntry]:
        return self._state.get(url)

    def save(self) -> None:
        """Persist state to JSON file."""
        if not self.state_file_path:
            return

        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = {k: v.to_dict() for k, v in self._state.items()}
        with open(self.state_file_path, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)

    def load(self) -> None:
        """Load state from JSON file."""
        if not self.state_file_path or not self.state_file_path.exists():
            return

        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._state = {k: CrawlStateEntry.from_dict(v) for k, v in data.items()}
        except Exception as e:
            logger.error("incremental_crawl_state_load_failed", error=str(e))
