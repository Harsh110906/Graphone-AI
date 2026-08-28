"""News entity schema — exact match to assessment spec."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.startup import Source


class NewsContent(BaseModel):
    """Content block for a News record."""

    title: str = Field(..., min_length=1, description="Article title")
    fullText: str = Field(
        ...,
        min_length=1,
        description="Full article text after boilerplate removal",
    )
    publishedAt: datetime = Field(
        ...,
        description="Publication timestamp in ISO-8601 — must be extracted, not assumed",
    )
    mentionedEntities: list[str] = Field(
        default_factory=list,
        description="Entity names mentioned in the article (for cross-referencing)",
    )

    model_config = {"extra": "forbid"}


class News(BaseModel):
    """
    Top-level News record — schema version 1.0.

    Only news published within the last 24 hours is accepted.
    publishedAt must come from the date-extraction waterfall, never assumed.
    """

    schemaVersion: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    recordType: str = Field(default="NEWS", pattern=r"^NEWS$")
    source: Source
    content: NewsContent
    collectedAt: datetime = Field(
        ...,
        description="ISO-8601 timestamp of when this record was collected",
    )

    model_config = {"extra": "forbid"}
