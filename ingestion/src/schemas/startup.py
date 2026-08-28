"""Startup entity schema — exact match to assessment spec."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


class Source(BaseModel):
    """Source provenance for any record."""

    name: str = Field(..., min_length=1, description="Source name (e.g., 'Crunchbase', 'Y Combinator')")
    url: HttpUrl = Field(..., description="Valid source URL — must be a real, working link")

    model_config = {"extra": "forbid"}


class StartupData(BaseModel):
    """Startup-specific data fields."""

    employeeCount: Optional[int] = Field(
        default=None,
        ge=0,
        description="Employee count — null if not verifiable from source. Never invent.",
    )

    model_config = {"extra": "forbid"}


class StartupContent(BaseModel):
    """Content block for a Startup record."""

    entityName: str = Field(
        ...,
        min_length=1,
        description="Canonical name after entity resolution",
    )
    data: StartupData = Field(default_factory=StartupData)

    model_config = {"extra": "forbid"}


class Startup(BaseModel):
    """
    Top-level Startup record — schema version 1.0.

    Every field must come from a real source. Missing values are null, never invented.
    """

    schemaVersion: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    recordType: str = Field(default="STARTUP", pattern=r"^STARTUP$")
    source: Source
    content: StartupContent
    collectedAt: datetime = Field(
        ...,
        description="ISO-8601 timestamp of when this record was collected",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_record_type(self) -> "Startup":
        if self.recordType != "STARTUP":
            raise ValueError(f"recordType must be 'STARTUP', got '{self.recordType}'")
        return self
