"""
Deterministic Entity Resolution Engine for AI Ecosystem Entities.

Resolution Hierarchy:
1. Exact Alias Match (Lookup in canonical seed alias map) -> Confidence: 1.00 -> ACCEPTED
2. Normalized Key Match (Unicode NFKD, lowercase, legal entity suffix stripping) -> Confidence: 0.98 -> ACCEPTED
3. Domain Context Match (Official website matching) -> Confidence: 0.95 -> ACCEPTED
4. Blocked Fuzzy Match (RapidFuzz Jaro-Winkler >= 0.92) -> Confidence: score -> ACCEPTED
5. Ambiguous Fuzzy Match (0.70 <= score < 0.92) -> Confidence: score -> REVIEW (never force-merged)
6. Novel Entity (score < 0.70 or no candidate) -> Confidence: 1.00 -> ACCEPTED (new canonical entry)

Logs every decision as an EntityMappingLog record with full auditability.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz.distance import JaroWinkler
import structlog

from src.schemas.entity_mapping import EntityMappingLog, MappingMethod, MappingDecision

logger = structlog.get_logger(__name__)

# Legal entity suffixes to strip for normalized matching
LEGAL_SUFFIX_REGEX = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|"
    r"pbc|public\s+benefit\s+corp|gmbh|sa|sas|srl|pty\s+ltd|pvt\s+ltd|"
    r"co|company|technologies|tech|ai|labs?|research)\b",
    re.IGNORECASE,
)


class EntityResolver:
    """
    Deterministic Entity Resolution Engine.
    Maps raw organization/startup strings to canonical entities.
    """

    def __init__(self, seed_file_path: Optional[str | Path] = None):
        self.seed_file_path = Path(seed_file_path) if seed_file_path else (
            Path(__file__).resolve().parent.parent.parent / "data" / "seed_entities.json"
        )
        self._canonical_entities: Dict[str, Dict[str, Any]] = {}
        self._alias_map: Dict[str, str] = {}           # exact lower alias -> canonical_name
        self._normalized_map: Dict[str, str] = {}      # normalized key -> canonical_name
        self._mapping_logs: List[dict[str, Any]] = []  # audit trail of all mappings
        self._load_seed_entities()

    def _load_seed_entities(self) -> None:
        """Load canonical entities and aliases from seed dataset."""
        if not self.seed_file_path.exists():
            logger.warning("seed_entities_not_found", path=str(self.seed_file_path))
            return

        try:
            with open(self.seed_file_path, "r", encoding="utf-8") as f:
                raw_json = json.load(f)

            entities = raw_json.get("entities", raw_json) if isinstance(raw_json, dict) else raw_json

            for ent in entities:
                name = ent.get("canonical_name", "")
                if not name:
                    continue
                self._canonical_entities[name] = ent

                # Index canonical name
                self._alias_map[name.lower()] = name
                norm_name = self.normalize_name(name)
                if norm_name:
                    self._normalized_map[norm_name] = name

                # Index aliases
                for alias in ent.get("aliases", []):
                    self._alias_map[alias.lower()] = name
                    norm_alias = self.normalize_name(alias)
                    if norm_alias:
                        self._normalized_map[norm_alias] = name

            logger.info("seed_entities_loaded", count=len(self._canonical_entities))
        except Exception as e:
            logger.error("seed_entities_load_failed", error=str(e))

    @staticmethod
    def normalize_name(name: str) -> str:
        """
        Normalize entity name:
        1. NFKD Unicode decomposition
        2. Lowercase
        3. Remove periods (so S.A.S. -> sas, Inc. -> inc)
        4. Strip punctuation to spaces
        5. Strip legal entity suffixes
        6. Collapse whitespace
        """
        if not name or not isinstance(name, str):
            return ""

        norm = unicodedata.normalize("NFKD", name)
        norm = "".join(c for c in norm if not unicodedata.combining(c)).lower()
        norm = norm.replace(".", "")
        norm = re.sub(r"[^\w\s]", " ", norm)
        norm = LEGAL_SUFFIX_REGEX.sub(" ", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        return norm

    def resolve(
        self,
        raw_name: str,
        domain: Optional[str] = None,
        source_url: str = "https://graphone.ai/entity-resolution",
    ) -> Tuple[Optional[str], MappingDecision, float, MappingMethod]:
        """
        Resolve a raw entity name against known canonical entities.

        Returns:
            (canonical_name, decision, confidence_score, mapping_method)
        """
        if not raw_name or not raw_name.strip():
            return None, MappingDecision.REJECTED, 0.0, MappingMethod.EXACT_ALIAS

        raw_trimmed = raw_name.strip()
        raw_lower = raw_trimmed.lower()

        # ── Stage 1: Exact Alias Match (Confidence 1.00) ──
        if raw_lower in self._alias_map:
            canonical = self._alias_map[raw_lower]
            self._record_mapping(raw_trimmed, canonical, MappingMethod.EXACT_ALIAS, 1.0, MappingDecision.ACCEPTED, source_url)
            return canonical, MappingDecision.ACCEPTED, 1.0, MappingMethod.EXACT_ALIAS

        # ── Stage 2: Normalized Name Match (Confidence 0.98) ──
        norm_key = self.normalize_name(raw_trimmed)
        if norm_key and norm_key in self._normalized_map:
            canonical = self._normalized_map[norm_key]
            self._record_mapping(raw_trimmed, canonical, MappingMethod.NORMALIZATION, 0.98, MappingDecision.ACCEPTED, source_url)
            return canonical, MappingDecision.ACCEPTED, 0.98, MappingMethod.NORMALIZATION

        # ── Stage 3: Domain Context Match if domain supplied (Confidence 0.95) ──
        if domain:
            cleaned_domain = domain.lower().replace("www.", "").strip()
            for c_name, data in self._canonical_entities.items():
                c_domain = data.get("domain") or data.get("official_domain")
                if c_domain and c_domain.lower().replace("www.", "") == cleaned_domain:
                    self._record_mapping(raw_trimmed, c_name, MappingMethod.CONTEXT_MATCH, 0.95, MappingDecision.ACCEPTED, source_url)
                    return c_name, MappingDecision.ACCEPTED, 0.95, MappingMethod.CONTEXT_MATCH

        # ── Stage 4: Blocked Fuzzy Match (RapidFuzz Jaro-Winkler) ──
        best_canonical = None
        best_score = 0.0

        for c_name in self._canonical_entities:
            score = JaroWinkler.similarity(norm_key, self.normalize_name(c_name))
            if score > best_score:
                best_score = score
                best_canonical = c_name

        if best_score >= 0.92 and best_canonical:
            # High-confidence fuzzy match -> ACCEPTED
            self._record_mapping(raw_trimmed, best_canonical, MappingMethod.FUZZY_MATCH, round(best_score, 4), MappingDecision.ACCEPTED, source_url)
            return best_canonical, MappingDecision.ACCEPTED, round(best_score, 4), MappingMethod.FUZZY_MATCH

        elif 0.70 <= best_score < 0.92 and best_canonical:
            # Ambiguous match -> Route to REVIEW queue (never force merge!)
            self._record_mapping(raw_trimmed, None, MappingMethod.MANUAL_REVIEW, round(best_score, 4), MappingDecision.REVIEW, source_url)
            logger.info("entity_routed_to_manual_review", raw_name=raw_trimmed, candidate=best_canonical, score=round(best_score, 4))
            return None, MappingDecision.REVIEW, round(best_score, 4), MappingMethod.MANUAL_REVIEW

        # ── Stage 5: Novel Entity (< 0.70) -> ACCEPTED (new entity) ──
        self._record_mapping(raw_trimmed, raw_trimmed, MappingMethod.EXACT_ALIAS, 1.0, MappingDecision.ACCEPTED, source_url)
        return raw_trimmed, MappingDecision.ACCEPTED, 1.0, MappingMethod.EXACT_ALIAS

    def _record_mapping(
        self,
        raw_name: str,
        canonical_name: Optional[str],
        method: MappingMethod,
        confidence: float,
        decision: MappingDecision,
        source_url: str = "https://graphone.ai/entity-resolution",
    ) -> None:
        """Create and store an audit log record for entity resolution."""
        log_entry = {
            "schemaVersion": "1.0",
            "recordType": "ENTITY_MAPPING_LOG",
            "rawName": raw_name,
            "canonicalName": canonical_name,
            "method": method.value if hasattr(method, "value") else str(method),
            "confidence": confidence,
            "sourceUrl": source_url,
            "decision": decision.value if hasattr(decision, "value") else str(decision),
        }
        # Schema validation
        try:
            EntityMappingLog(
                rawName=raw_name,
                canonicalName=canonical_name,
                method=method,
                confidence=confidence,
                sourceUrl=source_url,
                decision=decision,
            )
        except Exception as e:
            logger.error("entity_mapping_log_schema_error", error=str(e))

        self._mapping_logs.append(log_entry)

    @property
    def mapping_logs(self) -> List[dict[str, Any]]:
        """Return all recorded entity resolution logs."""
        return self._mapping_logs
