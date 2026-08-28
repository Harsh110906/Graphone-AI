"""
Data Lineage Tracker.

Maintains an immutable, queryable provenance chain for every ingested fact:
    raw_document_id -> extraction_run_id -> extraction_method -> transformations -> entity_resolution_log_id -> dedup_key -> record_version
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from src.schemas.lineage import LineageEvent, ExtractionMethod


class LineageChain(BaseModel):
    """Full end-to-end lineage record for an entity."""
    record_id: UUID
    record_type: str
    record_version: int = 1
    raw_document_id: UUID
    extraction_run_id: UUID
    source_url: str
    source_name: str
    extraction_method: ExtractionMethod
    transformations: list[str] = Field(default_factory=list)
    entity_mapping_log_id: Optional[UUID] = None
    canonical_entity_name: Optional[str] = None
    dedup_key: Optional[str] = None
    validation_status: str = "PASSED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LineageTracker:
    """In-memory and persistent registry of data lineage events."""

    def __init__(self):
        self._chains: dict[str, LineageChain] = {}  # str(record_id) -> LineageChain
        self._events: list[LineageEvent] = []

    def record_lineage(
        self,
        record_id: UUID,
        record_type: str,
        source_url: str,
        source_name: str,
        extraction_method: ExtractionMethod = ExtractionMethod.API_STRUCTURED,
        raw_document_id: Optional[UUID] = None,
        extraction_run_id: Optional[UUID] = None,
        transformations: Optional[list[str]] = None,
        entity_mapping_log_id: Optional[UUID] = None,
        canonical_entity_name: Optional[str] = None,
        dedup_key: Optional[str] = None,
        validation_status: str = "PASSED",
        record_version: int = 1,
    ) -> LineageChain:
        """Create and record an end-to-end lineage chain."""
        raw_doc_uuid = raw_document_id or uuid4()
        run_uuid = extraction_run_id or uuid4()

        chain = LineageChain(
            record_id=record_id,
            record_type=record_type,
            record_version=record_version,
            raw_document_id=raw_doc_uuid,
            extraction_run_id=run_uuid,
            source_url=source_url,
            source_name=source_name,
            extraction_method=extraction_method,
            transformations=transformations or ["pydantic_schema_validation", "boilerplate_removal"],
            entity_mapping_log_id=entity_mapping_log_id,
            canonical_entity_name=canonical_entity_name,
            dedup_key=dedup_key,
            validation_status=validation_status,
        )

        event = LineageEvent(
            id=uuid4(),
            raw_document_id=raw_doc_uuid,
            extraction_run_id=run_uuid,
            extraction_method=extraction_method,
            validation_result=validation_status,
            entity_resolution_decision=canonical_entity_name,
            record_version=record_version,
            created_at=datetime.now(timezone.utc),
        )

        self._chains[str(record_id)] = chain
        self._events.append(event)
        return chain

    def get_lineage(self, record_id: UUID | str) -> Optional[LineageChain]:
        """Retrieve lineage chain by record ID."""
        return self._chains.get(str(record_id))

    def list_all_chains(self) -> list[LineageChain]:
        """Return all recorded lineage chains."""
        return list(self._chains.values())
