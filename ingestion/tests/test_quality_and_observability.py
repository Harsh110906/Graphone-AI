"""
Unit tests for DataQualityScorer, LineageTracker, and MetricsCollector.
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.verification.quality_scorer import DataQualityScorer
from src.storage.lineage_tracker import LineageTracker
from src.observability.metrics import MetricsCollector
from src.schemas.lineage import ExtractionMethod


class TestDataQualityScorer:
    """Test suite for Data Quality Score calculations."""

    def test_high_quality_corroborated_fresh_record(self):
        """Authoritative, fresh, corroborated record scores high (>= 90)."""
        breakdown = DataQualityScorer.compute_score(
            source_name="arXiv API",
            source_url="https://export.arxiv.org/api/query?id_list=2412.20138",
            published_at=datetime.now(timezone.utc) - timedelta(hours=2),
            is_corroborated=True,
            is_disputed=False,
            extraction_method="api_structured",
        )

        assert breakdown.total_score >= 90.0
        assert breakdown.source_reliability == 100.0
        assert breakdown.corroboration == 100.0
        assert breakdown.freshness == 100.0
        assert breakdown.dispute_penalty == 0.0

    def test_disputed_record_receives_penalty(self):
        """Active dispute applies a 25 point penalty."""
        clean_breakdown = DataQualityScorer.compute_score(
            source_name="Curated Directory",
            source_url="https://steven2358.github.io",
            is_corroborated=False,
            is_disputed=False,
        )

        disputed_breakdown = DataQualityScorer.compute_score(
            source_name="Curated Directory",
            source_url="https://steven2358.github.io",
            is_corroborated=False,
            is_disputed=True,
        )

        assert disputed_breakdown.dispute_penalty == 25.0
        assert disputed_breakdown.total_score < clean_breakdown.total_score


class TestLineageTracker:
    """Test suite for data lineage tracking."""

    def test_record_and_get_lineage(self):
        tracker = LineageTracker()
        rec_id = uuid4()
        raw_doc_id = uuid4()

        chain = tracker.record_lineage(
            record_id=rec_id,
            record_type="STARTUP",
            source_url="https://openai.com/api/",
            source_name="Ecosystem Directory",
            raw_document_id=raw_doc_id,
            canonical_entity_name="OpenAI",
            dedup_key="STARTUP:openai",
            extraction_method=ExtractionMethod.HTML_PARSING,
        )

        fetched = tracker.get_lineage(rec_id)
        assert fetched is not None
        assert fetched.raw_document_id == raw_doc_id
        assert fetched.canonical_entity_name == "OpenAI"
        assert fetched.dedup_key == "STARTUP:openai"
        assert fetched.validation_status == "PASSED"


class TestObservabilityMetrics:
    """Test suite for operational telemetry and metrics reporting."""

    def test_record_and_generate_report(self):
        collector = MetricsCollector()

        collector.record_crawl(
            source_name="arXiv API",
            accepted=True,
            freshness_hours=1.5,
        )
        collector.record_crawl(
            source_name="arXiv API",
            accepted=False,
            is_duplicate=True,
        )
        collector.record_crawl(
            source_name="TechCrunch AI",
            accepted=False,
            is_stale=True,
            freshness_hours=48.0,
        )

        report = collector.generate_report()

        assert report.total_sources == 2
        assert report.total_records_ingested == 1
        assert report.total_duplicates_blocked == 1
        assert report.total_stale_rejected == 1
        assert report.system_status == "HEALTHY"
