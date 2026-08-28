"""
Deduplication engine.

Multi-layer dedup BEFORE storage:
1. Exact key match (URL, arxiv_id, domain)
2. Normalized key match (lowercase, strip, unicode normalize)
3. Blocked fuzzy match — ONLY within blocks to avoid O(n²)

Blocking strategy: group by first letter + domain/source type,
then fuzzy match only within blocks using RapidFuzz Jaro-Winkler.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

# Lazy import to avoid hard dependency at module level
_rapidfuzz_available = True
try:
    from rapidfuzz.distance import JaroWinkler
except ImportError:
    _rapidfuzz_available = False
    logger.warning("rapidfuzz_not_available", hint="Install rapidfuzz for fuzzy dedup")


@dataclass
class DeduplicationResult:
    """Result of a dedup check."""
    is_duplicate: bool
    match_type: Optional[str] = None       # "exact_key" | "normalized_key" | "fuzzy_match"
    matched_key: Optional[str] = None      # The key that was matched
    similarity_score: Optional[float] = None  # For fuzzy matches


class DeduplicationEngine:
    """
    Multi-layer deduplication engine.

    Maintains in-memory indices for fast dedup checks.
    Designed to be populated incrementally as records are ingested.

    For production at scale (500k+), these indices would be backed by
    Redis or PostgreSQL with ON CONFLICT DO NOTHING, but the logic is identical.
    """

    def __init__(self, fuzzy_threshold: float = 0.90):
        """
        Args:
            fuzzy_threshold: Minimum Jaro-Winkler similarity for fuzzy match (0.0-1.0).
                             0.90 is conservative — will catch "OpenAI" vs "Open AI" but not
                             "OpenAI" vs "Anthropic".
        """
        self.fuzzy_threshold = fuzzy_threshold

        # Layer 1: Exact key index (url -> record_key)
        self._exact_keys: set[str] = set()

        # Layer 2: Normalized key index
        self._normalized_keys: set[str] = set()

        # Layer 3: Blocked fuzzy index — block_key -> [normalized_names]
        self._fuzzy_blocks: dict[str, list[str]] = defaultdict(list)

        # Track what we've seen for auditing
        self._seen_count: int = 0
        self._duplicate_count: int = 0

    @staticmethod
    def normalize_key(value: str) -> str:
        """
        Normalize a string for dedup comparison.

        Steps:
        1. Unicode NFKD normalization
        2. Lowercase
        3. Strip whitespace
        4. Remove legal suffixes (Inc., Ltd., etc.)
        5. Remove punctuation except hyphens
        6. Collapse multiple spaces/hyphens
        """
        if not value:
            return ""

        # Unicode normalize
        s = unicodedata.normalize("NFKD", value)

        # Lowercase
        s = s.lower()

        # Remove legal suffixes
        legal_suffixes = [
            r"\binc\.?\b", r"\bltd\.?\b", r"\bllc\.?\b", r"\bcorp\.?\b",
            r"\bco\.?\b", r"\bpvt\.?\b", r"\bpbc\.?\b", r"\bgmbh\.?\b",
            r"\bs\.?a\.?\b", r"\bplc\.?\b", r"\bptyltd\.?\b",
        ]
        for suffix in legal_suffixes:
            s = re.sub(suffix, "", s, flags=re.IGNORECASE)

        # Remove punctuation except hyphens
        s = re.sub(r"[^\w\s-]", "", s)

        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()

        return s

    @staticmethod
    def extract_exact_key(record: dict[str, Any]) -> str | None:
        """
        Extract the exact dedup key based on record type.

        - RESEARCH_PAPER: arxiv_id or paper_url
        - STARTUP: official domain or normalized name
        - PRODUCT: source URL
        - JOB: source URL (canonical_url)
        - NEWS: source URL (canonical_url)
        """
        record_type = record.get("recordType", "")
        content = record.get("content", {})
        source = record.get("source", {})

        if record_type == "RESEARCH_PAPER":
            # Prefer arxiv_id from metadata, fall back to paper_url
            metadata = record.get("_metadata", {})
            arxiv_id = metadata.get("arxiv_id")
            if arxiv_id:
                return f"arxiv:{arxiv_id}"
            paper_url = content.get("paper_url", "")
            if paper_url:
                return f"url:{paper_url}"

        elif record_type == "STARTUP":
            # Domain-based key (unless shared aggregator hub like huggingface or github)
            source_url = str(source.get("url", ""))
            name = content.get("entityName", "")
            if source_url:
                domain = urlparse(source_url).netloc.lower().replace("www.", "")
                if domain and domain not in ("huggingface.co", "github.com", "raw.githubusercontent.com", "thataicollection.com"):
                    return f"startup_domain:{domain}"
                elif domain:
                    return f"startup_url:{source_url}"
            if name:
                return f"startup_name:{DeduplicationEngine.normalize_key(name)}"

        elif record_type in ("PRODUCT", "JOB", "NEWS"):
            source_url = source.get("url", "")
            if source_url:
                return f"url:{source_url}"

        return None

    @staticmethod
    def _compute_block_key(name: str, record_type: str) -> str:
        """
        Compute a blocking key for fuzzy matching.

        Uses first 2 characters of normalized name + record type.
        This limits fuzzy comparison to ~100-500 items per block instead of O(n²).
        """
        normalized = DeduplicationEngine.normalize_key(name)
        prefix = normalized[:2] if len(normalized) >= 2 else normalized
        return f"{record_type}:{prefix}"

    def check(self, record: dict[str, Any]) -> DeduplicationResult:
        """
        Check if a record is a duplicate.

        Returns DeduplicationResult with is_duplicate=True if matched at any layer.
        """
        self._seen_count += 1

        # ── Layer 1: Exact key match ──
        exact_key = self.extract_exact_key(record)
        if exact_key and exact_key in self._exact_keys:
            self._duplicate_count += 1
            logger.info("dedup_exact_match", key=exact_key)
            return DeduplicationResult(
                is_duplicate=True,
                match_type="exact_key",
                matched_key=exact_key,
            )

        # ── Layer 2: Normalized key match ──
        entity_name = self._get_entity_name(record)
        record_type = record.get("recordType", "")
        if entity_name:
            norm_key = f"{record_type}:{self.normalize_key(entity_name)}"
            if norm_key in self._normalized_keys:
                self._duplicate_count += 1
                logger.info("dedup_normalized_match", key=norm_key, raw_name=entity_name)
                return DeduplicationResult(
                    is_duplicate=True,
                    match_type="normalized_key",
                    matched_key=norm_key,
                )

        # ── Layer 3: Blocked fuzzy match ──
        if entity_name and _rapidfuzz_available:
            block_key = self._compute_block_key(entity_name, record_type)
            normalized_name = self.normalize_key(entity_name)

            for existing_name in self._fuzzy_blocks.get(block_key, []):
                score = JaroWinkler.similarity(normalized_name, existing_name)
                if score >= self.fuzzy_threshold:
                    self._duplicate_count += 1
                    logger.info(
                        "dedup_fuzzy_match",
                        raw_name=entity_name,
                        matched_name=existing_name,
                        similarity=round(score, 4),
                    )
                    return DeduplicationResult(
                        is_duplicate=True,
                        match_type="fuzzy_match",
                        matched_key=existing_name,
                        similarity_score=score,
                    )

        return DeduplicationResult(is_duplicate=False)

    def register(self, record: dict[str, Any]) -> None:
        """
        Register a record in all dedup indices.

        Call this AFTER check() returns is_duplicate=False.
        """
        # Register exact key
        exact_key = self.extract_exact_key(record)
        if exact_key:
            self._exact_keys.add(exact_key)

        # Register normalized key
        entity_name = self._get_entity_name(record)
        record_type = record.get("recordType", "")
        if entity_name:
            norm_key = f"{record_type}:{self.normalize_key(entity_name)}"
            self._normalized_keys.add(norm_key)

            # Register in fuzzy block
            block_key = self._compute_block_key(entity_name, record_type)
            normalized_name = self.normalize_key(entity_name)
            self._fuzzy_blocks[block_key].append(normalized_name)

    def check_and_register(self, record: dict[str, Any]) -> DeduplicationResult:
        """Check for duplicate, and register if not a duplicate."""
        result = self.check(record)
        if not result.is_duplicate:
            self.register(record)
        return result

    @staticmethod
    def _get_entity_name(record: dict[str, Any]) -> str | None:
        """Extract the entity name from a record based on its type."""
        content = record.get("content", {})
        record_type = record.get("recordType", "")

        if record_type == "STARTUP":
            return content.get("entityName")
        elif record_type == "PRODUCT":
            return content.get("startupName")
        elif record_type == "RESEARCH_PAPER":
            return content.get("title")
        elif record_type == "JOB":
            company = content.get("company", "")
            title = record.get("_metadata", {}).get("job_title") or source.get("url", "")
            return f"{company}:{title}" if company else None
        elif record_type == "NEWS":
            return content.get("title")
        return None

    @property
    def stats(self) -> dict[str, int]:
        """Return dedup statistics."""
        return {
            "total_seen": self._seen_count,
            "duplicates_found": self._duplicate_count,
            "unique_exact_keys": len(self._exact_keys),
            "unique_normalized_keys": len(self._normalized_keys),
            "fuzzy_blocks": len(self._fuzzy_blocks),
        }
