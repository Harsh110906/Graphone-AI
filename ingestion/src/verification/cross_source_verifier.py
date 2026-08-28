"""
Cross-Source Verification Engine.

Compares facts and field values extracted across independent sources.
Enforces Section 7 of the specification:
- VERIFIED: Independent sources agree on field value.
- DISPUTED: Independent sources disagree — both values retained with their source URLs.
- SINGLE_SOURCE: Only one source has reported this field value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from src.schemas.data_quality import DataQualityFlag, QualityFlagType, QualityStatus


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    SINGLE_SOURCE = "SINGLE_SOURCE"


class FieldObservation(BaseModel):
    """An observation of a specific field from an identified source."""
    field_name: str
    value: Any
    source_name: str
    source_url: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationResult(BaseModel):
    """Result of cross-source verification for an entity field."""
    entity_name: str
    field_name: str
    status: VerificationStatus
    canonical_value: Any
    observations: list[FieldObservation]
    disputed_values: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CrossSourceVerifier:
    """
    Cross-source fact verification and conflict resolution engine.
    """

    def __init__(self):
        self._observations: dict[str, list[FieldObservation]] = {}  # "entity:field" -> list[FieldObservation]
        self._results: dict[str, VerificationResult] = {}
        self._quality_flags: list[DataQualityFlag] = []

    def record_observation(
        self,
        entity_name: str,
        field_name: str,
        value: Any,
        source_name: str,
        source_url: str,
    ) -> FieldObservation:
        """Record a single field observation from a source."""
        key = f"{entity_name.strip().lower()}:{field_name.strip().lower()}"
        obs = FieldObservation(
            field_name=field_name,
            value=value,
            source_name=source_name,
            source_url=source_url,
        )
        if key not in self._observations:
            self._observations[key] = []
        self._observations[key].append(obs)
        return obs

    def verify_field(
        self,
        entity_name: str,
        field_name: str,
        record_id: Optional[UUID] = None,
        record_type: str = "ENTITY",
    ) -> VerificationResult:
        """
        Verify a field across all recorded observations for an entity.
        """
        key = f"{entity_name.strip().lower()}:{field_name.strip().lower()}"
        observations = self._observations.get(key, [])

        if not observations:
            res = VerificationResult(
                entity_name=entity_name,
                field_name=field_name,
                status=VerificationStatus.SINGLE_SOURCE,
                canonical_value=None,
                observations=[],
                confidence=0.0,
            )
            self._results[key] = res
            return res

        # Filter out null values for verification comparisons
        non_null_obs = [o for o in observations if o.value is not None]

        if len(non_null_obs) == 0:
            res = VerificationResult(
                entity_name=entity_name,
                field_name=field_name,
                status=VerificationStatus.SINGLE_SOURCE,
                canonical_value=None,
                observations=observations,
                confidence=0.5,
            )
            self._results[key] = res
            return res

        if len(non_null_obs) == 1:
            res = VerificationResult(
                entity_name=entity_name,
                field_name=field_name,
                status=VerificationStatus.SINGLE_SOURCE,
                canonical_value=non_null_obs[0].value,
                observations=observations,
                confidence=0.75,
            )
            self._results[key] = res
            return res

        # Compare distinct values across sources (normalizing strings)
        distinct_values: dict[str, list[FieldObservation]] = {}
        for obs in non_null_obs:
            norm_val = str(obs.value).strip().lower()
            if norm_val not in distinct_values:
                distinct_values[norm_val] = []
            distinct_values[norm_val].append(obs)

        if len(distinct_values) == 1:
            # Agreement across multiple independent sources -> VERIFIED
            canonical = non_null_obs[0].value
            res = VerificationResult(
                entity_name=entity_name,
                field_name=field_name,
                status=VerificationStatus.VERIFIED,
                canonical_value=canonical,
                observations=observations,
                confidence=1.0,
            )
            self._results[key] = res
            return res

        # Disagreement across sources -> DISPUTED
        disputed_list = [
            {
                "value": obs_list[0].value,
                "source_name": obs_list[0].source_name,
                "source_url": obs_list[0].source_url,
                "count": len(obs_list),
            }
            for obs_list in distinct_values.values()
        ]

        # In a dispute, pick the majority value or first observation, but flag dispute
        canonical = non_null_obs[0].value

        rec_uuid = record_id or uuid4()
        flag = DataQualityFlag(
            record_type=record_type,
            record_id=rec_uuid,
            flag_type=QualityFlagType.DISPUTED_VALUE,
            field_name=field_name,
            expected_value=str(disputed_list[0]["value"]),
            actual_value=str(disputed_list[1]["value"]),
            source_url=disputed_list[1]["source_url"],
            status=QualityStatus.DISPUTED,
            quality_score=45.0,  # Penalized due to active dispute
        )
        self._quality_flags.append(flag)

        res = VerificationResult(
            entity_name=entity_name,
            field_name=field_name,
            status=VerificationStatus.DISPUTED,
            canonical_value=canonical,
            observations=observations,
            disputed_values=disputed_list,
            confidence=0.45,
        )
        self._results[key] = res
        return res

    def get_quality_flags(self) -> list[DataQualityFlag]:
        """Return all generated quality flags."""
        return self._quality_flags
