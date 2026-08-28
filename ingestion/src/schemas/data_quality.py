"""Data quality flag schema — tracks quality issues and verification status."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class QualityFlagType(str, Enum):
    """Type of data quality issue."""
    MISSING_FIELD = "missing_field"
    DISPUTED_VALUE = "disputed_value"
    LOW_CONFIDENCE = "low_confidence"
    STALE_DATA = "stale_data"
    UNVERIFIED_SOURCE = "unverified_source"
    SCHEMA_VIOLATION = "schema_violation"
    DUPLICATE_SUSPECT = "duplicate_suspect"
    FRESHNESS_UNCERTAIN = "freshness_uncertain"


class QualityStatus(str, Enum):
    """Status of a quality flag."""
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    PENDING_REVIEW = "PENDING_REVIEW"


class DataQualityFlag(BaseModel):
    """
    Data quality flag — records quality issues for any entity record.

    Anything below confidence threshold or with disputed facts gets a flag.
    PENDING_REVIEW items are excluded from public search until resolved.
    """

    id: UUID = Field(default_factory=uuid4)
    record_type: str = Field(..., description="Entity type (STARTUP, PRODUCT, etc.)")
    record_id: UUID = Field(..., description="ID of the flagged record")
    flag_type: QualityFlagType = Field(..., description="Type of quality issue")
    field_name: str = Field(..., description="Name of the field with the issue")
    expected_value: Optional[str] = Field(default=None, description="Expected/first-source value")
    actual_value: Optional[str] = Field(default=None, description="Second-source/conflicting value")
    source_url: Optional[str] = Field(default=None, description="Source URL for the conflicting value")
    status: QualityStatus = Field(default=QualityStatus.OPEN)
    quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Data Quality Score (0-100) — weighted formula of source reliability, "
                    "corroboration, freshness, extraction confidence, and conflict flags",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = Field(default=None)

    model_config = {"extra": "forbid"}
