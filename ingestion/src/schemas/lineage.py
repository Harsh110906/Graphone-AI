"""Lineage event schema — tracks end-to-end data provenance."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ExtractionMethod(str, Enum):
    """How data was extracted from the source."""
    API_STRUCTURED = "api_structured"       # Direct API response (arXiv, GitHub)
    RSS_FEED = "rss_feed"                   # RSS/Atom feed parsing
    JSON_LD = "json_ld"                     # Structured JSON-LD / Meta extraction
    LLM_EXTRACTION = "llm_extraction"       # LLM-based extraction from text
    HTML_PARSING = "html_parsing"           # Rule-based HTML scraping
    BROWSER_RENDER = "browser_render"       # Playwright-rendered page
    MANUAL = "manual"                       # Human-entered data


class LineageEvent(BaseModel):
    """
    Data lineage record — every stored fact must be traceable back to:
    - The raw document it came from (raw_document_id)
    - The extraction method/model used
    - The timestamp of extraction

    This is a non-negotiable requirement: no fact exists without lineage.
    """

    id: UUID = Field(default_factory=uuid4)
    raw_document_id: UUID = Field(
        ...,
        description="ID of the raw document this fact was extracted from",
    )
    extraction_run_id: UUID = Field(
        ...,
        description="ID of the extraction pipeline run",
    )
    extraction_method: ExtractionMethod = Field(
        ...,
        description="How the data was extracted",
    )
    llm_model_used: Optional[str] = Field(
        default=None,
        description="LLM model identifier if extraction_method is llm_extraction",
    )
    validation_result: str = Field(
        ...,
        description="'PASSED' | 'FAILED' | 'PARTIAL' — schema validation outcome",
    )
    entity_resolution_decision: Optional[str] = Field(
        default=None,
        description="Entity resolution decision if applicable",
    )
    record_version: int = Field(
        default=1,
        ge=1,
        description="Version number of this record (incremented on updates)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"extra": "forbid"}
