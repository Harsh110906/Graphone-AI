"""
Data Quality Scorer (0-100).

Implements the multi-factor Data Quality Score formula from Section 7:
    Score = w_rel * S_rel + w_corrob * S_corrob + w_fresh * S_fresh + w_conf * S_conf - P_dispute

Component Breakdown:
- Source Reliability (w=0.30): Official API / Primary RSS = 100, Curated Directory = 85, General Web Crawl = 70.
- Corroboration (w=0.25): Multi-source verified = 100, Single-source validated = 75, Unverified = 50.
- Freshness (w=0.25): <= 24 hours = 100, <= 7 days = 85, <= 30 days = 70, Older/Unknown = 50.
- Extraction Confidence (w=0.20): Structured API/Exact regex = 100, HTML Selector/Heuristic = 85, Fuzzy = 70.
- Dispute Penalty: -25 points if active dispute flag exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    """Component breakdown of Data Quality Score."""
    source_reliability: float = Field(..., description="Source authority score (0-100)")
    corroboration: float = Field(..., description="Multi-source corroboration score (0-100)")
    freshness: float = Field(..., description="Temporal recency score (0-100)")
    extraction_confidence: float = Field(..., description="Extraction precision score (0-100)")
    dispute_penalty: float = Field(default=0.0, description="Deduction for active disputes (0-30)")
    total_score: float = Field(..., ge=0.0, le=100.0, description="Weighted composite score (0-100)")


class DataQualityScorer:
    """Computes transparent, componentized Data Quality Scores."""

    # Weights sum to 1.00
    W_RELIABILITY = 0.30
    W_CORROBORATION = 0.25
    W_FRESHNESS = 0.25
    W_CONFIDENCE = 0.20

    @classmethod
    def compute_score(
        cls,
        source_name: str,
        source_url: str,
        collected_at: Optional[datetime] = None,
        published_at: Optional[datetime] = None,
        is_corroborated: bool = False,
        is_disputed: bool = False,
        extraction_method: str = "api_structured",
        has_null_required_fields: bool = False,
    ) -> ScoreBreakdown:
        """
        Compute the composite Data Quality Score and component breakdown.
        """
        # 1. Source Reliability (0-100)
        rel_score = cls._score_source_reliability(source_name, source_url)

        # 2. Corroboration (0-100)
        # Genuinely cross-verified against >= 2 independent sources = 100.0
        # Authoritative primary registry (arXiv API, Greenhouse direct API) single-source = 80.0
        # Curated directory / web single-source = 70.0 (or 50.0 if missing fields)
        if is_corroborated:
            corrob_score = 100.0
        elif rel_score >= 95.0:
            # Authoritative primary registry single-source
            corrob_score = 80.0 if not has_null_required_fields else 65.0
        else:
            corrob_score = 70.0 if not has_null_required_fields else 50.0

        # 3. Freshness (0-100)
        fresh_score = cls._score_freshness(published_at or collected_at)

        # 4. Extraction Confidence (0-100)
        conf_score = cls._score_confidence(extraction_method)

        # 5. Dispute Penalty
        dispute_penalty = 25.0 if is_disputed else 0.0

        # Weighted calculation
        raw_total = (
            cls.W_RELIABILITY * rel_score
            + cls.W_CORROBORATION * corrob_score
            + cls.W_FRESHNESS * fresh_score
            + cls.W_CONFIDENCE * conf_score
            - dispute_penalty
        )

        total_score = max(0.0, min(100.0, round(raw_total, 2)))

        return ScoreBreakdown(
            source_reliability=rel_score,
            corroboration=corrob_score,
            freshness=fresh_score,
            extraction_confidence=conf_score,
            dispute_penalty=dispute_penalty,
            total_score=total_score,
        )

    @staticmethod
    def _score_source_reliability(name: str, url: str) -> float:
        """Evaluate source authority."""
        url_lower = url.lower()
        name_lower = name.lower()

        # Primary APIs and authoritative repositories
        if any(k in url_lower for k in [
            "arxiv.org", "api.github.com", "boards-api.greenhouse.io", "huggingface.co/api"
        ]):
            return 100.0

        # Primary RSS / Media Feeds
        if any(k in url_lower for k in ["techcrunch.com", "venturebeat.com", "remoteok.com"]):
            return 92.0

        # Curated Repositories & Lists
        if any(k in url_lower for k in ["steven2358", "open-llms", "paperswithcode.com"]):
            return 85.0

        # General web
        return 70.0

    @staticmethod
    def _score_freshness(ts: Optional[datetime]) -> float:
        """Evaluate temporal recency."""
        if not ts:
            return 50.0

        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        age_hours = (now - ts).total_seconds() / 3600.0

        if age_hours <= 24.0:
            return 100.0
        elif age_hours <= 24.0 * 7:
            return 85.0
        elif age_hours <= 24.0 * 30:
            return 70.0
        else:
            return 55.0

    @staticmethod
    def _score_confidence(method: str) -> float:
        """Evaluate extraction precision based on method."""
        method_lower = method.lower()
        if method_lower in ["api_structured", "rss_feed"]:
            return 100.0
        elif method_lower in ["html_parsing", "json_ld"]:
            return 90.0
        elif method_lower in ["browser_render", "css_selector"]:
            return 80.0
        elif method_lower in ["llm_extraction", "fuzzy"]:
            return 75.0
        return 70.0
