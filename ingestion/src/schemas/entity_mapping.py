"""Entity Mapping Log schema — for audit trail of every resolution decision."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class MappingMethod(str, Enum):
    """Method used for entity resolution."""
    EXACT_ALIAS = "exact_alias"
    NORMALIZATION = "normalization"
    FUZZY_MATCH = "fuzzy_match"
    CONTEXT_MATCH = "context_match"
    MANUAL_REVIEW = "manual_review"


class MappingDecision(str, Enum):
    """Decision outcome of entity resolution."""
    ACCEPTED = "ACCEPTED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"


class EntityMappingLog(BaseModel):
    """
    Audit record for every entity resolution decision.

    Every resolution attempt — successful or not — must produce one of these records.
    """

    rawName: str = Field(..., min_length=1, description="Original name as found in source")
    canonicalName: Optional[str] = Field(
        default=None,
        description="Resolved canonical name — null if resolution failed or sent to review",
    )
    method: MappingMethod = Field(..., description="Resolution method used")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the resolution (0.0-1.0)",
    )
    sourceUrl: HttpUrl = Field(..., description="Source URL where the raw name was found")
    decision: MappingDecision = Field(..., description="Final decision for this resolution")

    model_config = {"extra": "forbid"}
