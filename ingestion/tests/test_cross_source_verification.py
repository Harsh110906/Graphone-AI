"""
Unit tests for CrossSourceVerifier.
"""

import pytest
from src.verification.cross_source_verifier import CrossSourceVerifier, VerificationStatus
from src.schemas.data_quality import QualityStatus, QualityFlagType


class TestCrossSourceVerifier:
    """Test suite for cross-source fact verification."""

    def test_sources_agree_results_in_verified(self):
        """Two independent sources agreeing on a value produces status=VERIFIED."""
        verifier = CrossSourceVerifier()

        # Observation 1: Awesome Generative AI directory reports Llama is Free open source
        verifier.record_observation(
            entity_name="Llama",
            field_name="pricingModel",
            value="FREE",
            source_name="Curated AI Directory",
            source_url="https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md",
        )

        # Observation 2: Hugging Face Meta-Llama model card reports Free community license
        verifier.record_observation(
            entity_name="Llama",
            field_name="pricingModel",
            value="FREE",
            source_name="Hugging Face Model Card",
            source_url="https://huggingface.co/meta-llama/Llama-3.1-8B",
        )

        result = verifier.verify_field(entity_name="Llama", field_name="pricingModel")

        assert result.status == VerificationStatus.VERIFIED
        assert result.canonical_value == "FREE"
        assert result.confidence == 1.0
        assert len(result.observations) == 2
        assert len(verifier.get_quality_flags()) == 0

    def test_sources_disagree_results_in_disputed_and_flag(self):
        """Two independent sources disagreeing produces status=DISPUTED and quality flag."""
        verifier = CrossSourceVerifier()

        # Observation 1: Local tool catalog lists tool as Free
        verifier.record_observation(
            entity_name="Cursor",
            field_name="pricingModel",
            value="FREE",
            source_name="Open Tool Catalog",
            source_url="https://open-tools.dev/cursor",
        )

        # Observation 2: Official pricing page lists tool as Paid Pro subscription
        verifier.record_observation(
            entity_name="Cursor",
            field_name="pricingModel",
            value="PAID",
            source_name="Cursor Pricing Page",
            source_url="https://cursor.com/pricing",
        )

        result = verifier.verify_field(
            entity_name="Cursor",
            field_name="pricingModel",
            record_type="PRODUCT",
        )

        assert result.status == VerificationStatus.DISPUTED
        assert len(result.disputed_values) == 2
        assert result.confidence < 0.60

        # Confirm Quality Flag was created
        flags = verifier.get_quality_flags()
        assert len(flags) == 1
        flag = flags[0]
        assert flag.flag_type == QualityFlagType.DISPUTED_VALUE
        assert flag.status == QualityStatus.DISPUTED
        assert flag.field_name == "pricingModel"
        assert flag.expected_value == "FREE"
        assert flag.actual_value == "PAID"
        assert flag.source_url == "https://cursor.com/pricing"

    def test_single_source_results_in_single_source_status(self):
        """Single observation produces status=SINGLE_SOURCE."""
        verifier = CrossSourceVerifier()

        verifier.record_observation(
            entity_name="Anthropic",
            field_name="official_domain",
            value="anthropic.com",
            source_name="Greenhouse Job Board",
            source_url="https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        )

        result = verifier.verify_field(entity_name="Anthropic", field_name="official_domain")

        assert result.status == VerificationStatus.SINGLE_SOURCE
        assert result.canonical_value == "anthropic.com"
        assert result.confidence == 0.75
