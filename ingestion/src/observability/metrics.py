"""
Observability and Metrics Engine.

Collects real-time operational telemetry across all crawlers and pipelines:
- Source Freshness (avg age, max age, fresh vs stale count)
- Ingestion Volume (raw crawled vs valid schema vs duplicates blocked)
- Pipeline Errors (HTTP 429 backoffs, timeouts, parse failures)
- Schema Drift (fields present vs expected, extra fields blocked)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class SourceMetrics(BaseModel):
    """Metrics for a single data source."""
    source_name: str
    total_crawled: int = 0
    accepted_valid: int = 0
    duplicate_blocked: int = 0
    stale_rejected: int = 0
    parse_errors: int = 0
    http_429_backoffs: int = 0
    http_timeouts: int = 0
    avg_freshness_hours: Optional[float] = None
    last_crawled_at: Optional[datetime] = None
    schema_drift_alerts: list[str] = Field(default_factory=list)


class ObservabilityReport(BaseModel):
    """Global system health and observability report."""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_sources: int = 0
    total_records_ingested: int = 0
    total_duplicates_blocked: int = 0
    total_stale_rejected: int = 0
    sources: dict[str, SourceMetrics] = Field(default_factory=dict)
    system_status: str = "HEALTHY"


class MetricsCollector:
    """Singleton/Instance collector for crawler pipeline telemetry."""

    def __init__(self):
        self._sources: dict[str, SourceMetrics] = {}

    def get_or_create_source(self, source_name: str) -> SourceMetrics:
        if source_name not in self._sources:
            self._sources[source_name] = SourceMetrics(source_name=source_name)
        return self._sources[source_name]

    def record_crawl(
        self,
        source_name: str,
        accepted: bool = True,
        is_duplicate: bool = False,
        is_stale: bool = False,
        is_error: bool = False,
        freshness_hours: Optional[float] = None,
        is_429: bool = False,
        is_timeout: bool = False,
    ):
        """Record telemetry for a single crawled item."""
        m = self.get_or_create_source(source_name)
        m.total_crawled += 1
        m.last_crawled_at = datetime.now(timezone.utc)

        if accepted:
            m.accepted_valid += 1
        if is_duplicate:
            m.duplicate_blocked += 1
        if is_stale:
            m.stale_rejected += 1
        if is_error:
            m.parse_errors += 1
        if is_429:
            m.http_429_backoffs += 1
        if is_timeout:
            m.http_timeouts += 1

        if freshness_hours is not None:
            if m.avg_freshness_hours is None:
                m.avg_freshness_hours = round(freshness_hours, 2)
            else:
                m.avg_freshness_hours = round((m.avg_freshness_hours * 0.8) + (freshness_hours * 0.2), 2)

    def record_schema_drift(self, source_name: str, issue_description: str):
        """Record a schema drift or validation irregularity."""
        m = self.get_or_create_source(source_name)
        m.schema_drift_alerts.append(f"{datetime.now(timezone.utc).isoformat()}: {issue_description}")

    def generate_report(self) -> ObservabilityReport:
        """Compile a full observability report."""
        total_ingested = sum(s.accepted_valid for s in self._sources.values())
        total_dups = sum(s.duplicate_blocked for s in self._sources.values())
        total_stale = sum(s.stale_rejected for s in self._sources.values())
        total_errors = sum(s.parse_errors + s.http_429_backoffs for s in self._sources.values())

        status = "HEALTHY"
        if total_errors > 50:
            status = "DEGRADED"

        return ObservabilityReport(
            total_sources=len(self._sources),
            total_records_ingested=total_ingested,
            total_duplicates_blocked=total_dups,
            total_stale_rejected=total_stale,
            sources=self._sources,
            system_status=status,
        )


# Global collector instance
global_metrics = MetricsCollector()
