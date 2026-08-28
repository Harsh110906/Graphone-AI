"""Research Paper entity schema — exact match to assessment spec."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class ResearchPaperContent(BaseModel):
    """Content block for a Research Paper record."""

    title: str = Field(..., min_length=1, description="Paper title")
    authors: list[str] = Field(
        default_factory=list,
        description="List of author names — empty list if not available, never invented names",
    )
    paper_url: HttpUrl = Field(..., description="URL to the paper (arXiv, DOI, etc.)")
    github_url: Optional[HttpUrl] = Field(
        default=None,
        description="GitHub repo URL if linked — null if not available",
    )
    github_stars: Optional[int] = Field(
        default=None,
        ge=0,
        description="Live star count from GitHub API — null if no repo or API unavailable. Never guess.",
    )
    published_date: datetime = Field(
        ...,
        description="Publication date in ISO-8601",
    )

    model_config = {"extra": "forbid"}


class ResearchPaper(BaseModel):
    """
    Top-level Research Paper record — schema version 1.0.

    github_stars must come from the GitHub API, never from an LLM or estimate.
    """

    schemaVersion: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    recordType: str = Field(default="RESEARCH_PAPER", pattern=r"^RESEARCH_PAPER$")
    content: ResearchPaperContent
    collectedAt: datetime = Field(
        default_factory=datetime.utcnow,
        description="ISO-8601 timestamp of when this record was collected",
    )

    model_config = {"extra": "forbid"}
