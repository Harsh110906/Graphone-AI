"""Job entity schema — exact match to assessment spec."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.schemas.startup import Source


class RoleFamily(str, Enum):
    """Job role family classification."""
    ENGINEERING = "Engineering"
    PRODUCT = "Product"
    RESEARCH = "Research"
    SALES = "Sales"
    DESIGN = "Design"
    MARKETING = "Marketing"
    OPERATIONS = "Operations"
    DATA = "Data"
    OTHER = "Other"


class JobContent(BaseModel):
    """Content block for a Job record."""

    company: str = Field(
        ...,
        min_length=1,
        description="Canonical company name (after entity resolution)",
    )
    date: datetime = Field(
        ...,
        description="Job posting date in ISO-8601 — must be verified, not assumed",
    )
    is_remote: bool = Field(
        ...,
        description="Whether the job allows remote work",
    )
    role_family: RoleFamily = Field(
        ...,
        description="Role family classification",
    )

    model_config = {"extra": "forbid"}


class Job(BaseModel):
    """
    Top-level Job record — schema version 1.0.

    Only jobs published within the last 24 hours are accepted.
    """

    schemaVersion: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    recordType: str = Field(default="JOB", pattern=r"^JOB$")
    source: Source
    content: JobContent
    collectedAt: datetime = Field(
        ...,
        description="ISO-8601 timestamp of when this record was collected",
    )

    model_config = {"extra": "forbid"}
