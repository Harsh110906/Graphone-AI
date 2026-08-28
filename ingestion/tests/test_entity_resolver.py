"""
Unit tests for Deterministic Entity Resolution Engine.

Verifies:
- Stage 1: Exact alias match -> ACCEPTED (confidence 1.0)
- Stage 2: Normalized name match -> ACCEPTED (confidence 0.98)
- Stage 3: Domain match -> ACCEPTED (confidence 0.95)
- Stage 4: High-confidence fuzzy match (>= 0.92) -> ACCEPTED
- Stage 5: Ambiguous fuzzy match (0.70 <= score < 0.92) -> REVIEW (never force-merged)
- Stage 6: Novel entity (< 0.70) -> ACCEPTED (new canonical entry)
- Audit trail logging in EntityMappingLog schema
"""

from pathlib import Path
import pytest

from src.storage.entity_resolver import EntityResolver
from src.schemas.entity_mapping import MappingDecision, MappingMethod


class TestEntityResolver:
    """Test suite for deterministic entity resolution hierarchy."""

    @pytest.fixture
    def resolver(self) -> EntityResolver:
        return EntityResolver()

    def test_exact_alias_match(self, resolver: EntityResolver):
        """'OpenAI Inc.' or 'OpenAI' resolves exactly to canonical 'OpenAI'."""
        canonical, decision, score, method = resolver.resolve("OpenAI Inc")
        assert canonical == "OpenAI"
        assert decision == MappingDecision.ACCEPTED
        assert score >= 0.98

        canonical2, decision2, score2, method2 = resolver.resolve("Anthropic PBC")
        assert canonical2 == "Anthropic"
        assert decision2 == MappingDecision.ACCEPTED
        assert score2 >= 0.98

    def test_normalized_name_match(self, resolver: EntityResolver):
        """Unicode accents and legal suffixes are stripped."""
        canonical, decision, score, method = resolver.resolve("Místral AI S.A.S.")
        assert canonical == "Mistral AI"
        assert decision == MappingDecision.ACCEPTED
        assert method in (MappingMethod.NORMALIZATION, MappingMethod.EXACT_ALIAS, MappingMethod.FUZZY_MATCH)

    def test_domain_context_match(self, resolver: EntityResolver):
        """Domain match resolves entity when name has slight variation."""
        canonical, decision, score, method = resolver.resolve("Cohere Technologies", domain="cohere.com")
        assert canonical == "Cohere"
        assert decision == MappingDecision.ACCEPTED

    def test_high_confidence_fuzzy_match(self, resolver: EntityResolver):
        """Very close spelling (>= 0.92) auto-merges."""
        canonical, decision, score, method = resolver.resolve("StabilityAI")
        assert canonical == "Stability AI"
        assert decision == MappingDecision.ACCEPTED
        assert score >= 0.92

    def test_ambiguous_match_routes_to_manual_review(self, resolver: EntityResolver):
        """
        CRITICAL TEST: Ambiguous variant (score between 0.70 and 0.91)
        MUST be routed to REVIEW and NEVER force-merged.
        """
        canonical, decision, score, method = resolver.resolve("Anthropic Group Development")
        assert decision == MappingDecision.REVIEW
        assert canonical is None
        assert 0.70 <= score < 0.92
        assert method == MappingMethod.MANUAL_REVIEW

    def test_novel_entity_creates_new(self, resolver: EntityResolver):
        """Completely novel entity (< 0.70) creates a new record."""
        canonical, decision, score, method = resolver.resolve("QuantumBiotech NewCo 2026")
        assert decision == MappingDecision.ACCEPTED
        assert canonical == "QuantumBiotech NewCo 2026"

    def test_audit_logs_recorded(self, resolver: EntityResolver):
        """All resolutions produce audit log records matching EntityMappingLog schema."""
        resolver.resolve("OpenAI")
        resolver.resolve("Ambiguous Org Example")

        logs = resolver.mapping_logs
        assert len(logs) >= 2
        assert logs[-1]["recordType"] == "ENTITY_MAPPING_LOG"
        assert logs[-1]["decision"] in [d.value for d in MappingDecision]
