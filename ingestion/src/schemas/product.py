"""Product entity schema — exact match to assessment spec."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.schemas.startup import Source


class PricingModel(str, Enum):
    """Allowed pricing model values."""
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


class ProductContent(BaseModel):
    """Content block for a Product record."""

    startupName: Optional[str] = Field(
        default=None,
        description="Canonical startup name (after entity resolution) — null if not verifiable from source",
    )
    pricingModel: Optional[PricingModel] = Field(
        default=None,
        description="Pricing model — null if not verifiable from source",
    )

    model_config = {"extra": "forbid"}


class Product(BaseModel):
    """
    Top-level Product record — schema version 1.0.

    Every field must come from a real source. Missing values are null, never invented.
    """

    schemaVersion: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    recordType: str = Field(default="PRODUCT", pattern=r"^PRODUCT$")
    source: Source
    content: ProductContent
    collectedAt: datetime = Field(
        ...,
        description="ISO-8601 timestamp of when this record was collected",
    )

    model_config = {"extra": "forbid"}
