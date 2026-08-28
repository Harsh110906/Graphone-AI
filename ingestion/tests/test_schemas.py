"""
Comprehensive tests for all Pydantic entity schemas.

Tests cover:
- Valid construction with all fields
- Null handling for optional fields
- URL validation (must be valid HTTP/HTTPS)
- Date parsing and ISO-8601 compliance
- Enum enforcement (PricingModel, RoleFamily)
- Rejection of extra/invented fields (extra="forbid")
- Edge cases: empty authors, very long titles, unicode entity names
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.startup import Startup, StartupContent, StartupData, Source
from src.schemas.product import Product, ProductContent, PricingModel
from src.schemas.research_paper import ResearchPaper, ResearchPaperContent
from src.schemas.job import Job, JobContent, RoleFamily
from src.schemas.news import News, NewsContent
from src.schemas.entity_mapping import EntityMappingLog, MappingMethod, MappingDecision
from src.schemas.lineage import LineageEvent, ExtractionMethod
from src.schemas.data_quality import DataQualityFlag, QualityFlagType, QualityStatus


# ═══════════════════════════════════════════════════════════════
# Startup Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestStartupSchema:
    """Tests for the Startup entity schema."""

    def test_valid_startup(self):
        """A valid startup record should construct without errors."""
        startup = Startup(
            source=Source(name="Crunchbase", url="https://crunchbase.com/openai"),
            content=StartupContent(
                entityName="OpenAI",
                data=StartupData(employeeCount=1500),
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert startup.schemaVersion == "1.0"
        assert startup.recordType == "STARTUP"
        assert startup.content.entityName == "OpenAI"
        assert startup.content.data.employeeCount == 1500

    def test_startup_null_employee_count(self):
        """Employee count should accept null (not verifiable)."""
        startup = Startup(
            source=Source(name="Test", url="https://example.com"),
            content=StartupContent(
                entityName="Unknown Corp",
                data=StartupData(employeeCount=None),
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert startup.content.data.employeeCount is None

    def test_startup_default_data(self):
        """StartupData should default to null employeeCount."""
        startup = Startup(
            source=Source(name="Test", url="https://example.com"),
            content=StartupContent(entityName="Test Corp"),
            collectedAt=datetime.now(timezone.utc),
        )
        assert startup.content.data.employeeCount is None

    def test_startup_rejects_extra_fields(self):
        """Extra fields must be rejected (no invented data)."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Startup(
                source=Source(name="Test", url="https://example.com"),
                content=StartupContent(entityName="Test"),
                collectedAt=datetime.now(timezone.utc),
                invented_field="should fail",
            )

    def test_startup_rejects_invalid_url(self):
        """Source URL must be a valid URL."""
        with pytest.raises(ValidationError):
            Source(name="Test", url="not-a-url")

    def test_startup_rejects_empty_name(self):
        """Entity name must not be empty."""
        with pytest.raises(ValidationError):
            StartupContent(entityName="")

    def test_startup_rejects_negative_employees(self):
        """Employee count must be >= 0."""
        with pytest.raises(ValidationError):
            StartupData(employeeCount=-5)

    def test_startup_unicode_name(self):
        """Entity names with unicode characters should be accepted."""
        startup = Startup(
            source=Source(name="Test", url="https://example.com"),
            content=StartupContent(entityName="Ünïcödé Cörp™"),
            collectedAt=datetime.now(timezone.utc),
        )
        assert startup.content.entityName == "Ünïcödé Cörp™"

    def test_startup_wrong_record_type(self):
        """Record type must be exactly 'STARTUP'."""
        with pytest.raises(ValidationError):
            Startup(
                schemaVersion="1.0",
                recordType="PRODUCT",
                source=Source(name="Test", url="https://example.com"),
                content=StartupContent(entityName="Test"),
                collectedAt=datetime.now(timezone.utc),
            )


# ═══════════════════════════════════════════════════════════════
# Product Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestProductSchema:
    """Tests for the Product entity schema."""

    def test_valid_product(self):
        product = Product(
            source=Source(name="ProductHunt", url="https://producthunt.com/posts/chatgpt"),
            content=ProductContent(
                startupName="OpenAI",
                pricingModel=PricingModel.FREEMIUM,
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert product.content.pricingModel == PricingModel.FREEMIUM

    def test_product_null_pricing(self):
        """Pricing model can be null (not verifiable)."""
        product = Product(
            source=Source(name="Test", url="https://example.com"),
            content=ProductContent(startupName="Test", pricingModel=None),
            collectedAt=datetime.now(timezone.utc),
        )
        assert product.content.pricingModel is None

    def test_product_null_startup_name(self):
        """Startup name can be null if parent company cannot be determined."""
        product = Product(
            source=Source(name="Test", url="https://example.com"),
            content=ProductContent(startupName=None, pricingModel=PricingModel.FREE),
            collectedAt=datetime.now(timezone.utc),
        )
        assert product.content.startupName is None

    def test_product_rejects_invalid_pricing(self):
        """Invalid pricing model must be rejected."""
        with pytest.raises(ValidationError):
            ProductContent(startupName="Test", pricingModel="SUBSCRIPTION")

    def test_product_all_pricing_models(self):
        """All valid pricing models should be accepted."""
        for model in PricingModel:
            content = ProductContent(startupName="Test", pricingModel=model)
            assert content.pricingModel == model

    def test_product_rejects_extra_content_fields(self):
        """Extra fields in content must be rejected."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ProductContent(
                startupName="Test",
                pricingModel=PricingModel.FREE,
                invented="bad",
            )


# ═══════════════════════════════════════════════════════════════
# Research Paper Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestResearchPaperSchema:
    """Tests for the Research Paper entity schema."""

    def test_valid_paper(self):
        paper = ResearchPaper(
            content=ResearchPaperContent(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani", "Noam Shazeer"],
                paper_url="https://arxiv.org/abs/1706.03762",
                github_url="https://github.com/tensorflow/tensor2tensor",
                github_stars=15000,
                published_date=datetime(2017, 6, 12, tzinfo=timezone.utc),
            ),
        )
        assert paper.content.title == "Attention Is All You Need"
        assert len(paper.content.authors) == 2

    def test_paper_null_github(self):
        """GitHub fields should accept null."""
        paper = ResearchPaper(
            content=ResearchPaperContent(
                title="Test Paper",
                authors=["Author One"],
                paper_url="https://arxiv.org/abs/2301.00001",
                github_url=None,
                github_stars=None,
                published_date=datetime.now(timezone.utc),
            ),
        )
        assert paper.content.github_url is None
        assert paper.content.github_stars is None

    def test_paper_empty_authors(self):
        """Empty authors list should be accepted (some papers lack metadata)."""
        paper = ResearchPaper(
            content=ResearchPaperContent(
                title="Anonymous Paper",
                authors=[],
                paper_url="https://arxiv.org/abs/2301.00002",
                published_date=datetime.now(timezone.utc),
            ),
        )
        assert paper.content.authors == []

    def test_paper_rejects_negative_stars(self):
        """Stars must be >= 0."""
        with pytest.raises(ValidationError):
            ResearchPaperContent(
                title="Test",
                paper_url="https://arxiv.org/abs/2301.00003",
                github_stars=-1,
                published_date=datetime.now(timezone.utc),
            )

    def test_paper_very_long_title(self):
        """Very long titles should be accepted (some papers have long titles)."""
        long_title = "A" * 2000
        paper = ResearchPaper(
            content=ResearchPaperContent(
                title=long_title,
                paper_url="https://arxiv.org/abs/2301.00004",
                published_date=datetime.now(timezone.utc),
            ),
        )
        assert len(paper.content.title) == 2000


# ═══════════════════════════════════════════════════════════════
# Job Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestJobSchema:
    """Tests for the Job entity schema."""

    def test_valid_job(self):
        job = Job(
            source=Source(name="Lever", url="https://jobs.lever.co/openai/12345"),
            content=JobContent(
                company="OpenAI",
                date=datetime.now(timezone.utc),
                is_remote=True,
                role_family=RoleFamily.ENGINEERING,
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert job.content.is_remote is True
        assert job.content.role_family == RoleFamily.ENGINEERING

    def test_job_all_role_families(self):
        """All role families should be valid."""
        for family in RoleFamily:
            content = JobContent(
                company="Test",
                date=datetime.now(timezone.utc),
                is_remote=False,
                role_family=family,
            )
            assert content.role_family == family

    def test_job_rejects_invalid_role_family(self):
        """Invalid role family must be rejected."""
        with pytest.raises(ValidationError):
            JobContent(
                company="Test",
                date=datetime.now(timezone.utc),
                is_remote=False,
                role_family="InvalidFamily",
            )


# ═══════════════════════════════════════════════════════════════
# News Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestNewsSchema:
    """Tests for the News entity schema."""

    def test_valid_news(self):
        news = News(
            source=Source(name="TechCrunch", url="https://techcrunch.com/article/123"),
            content=NewsContent(
                title="OpenAI Launches GPT-5",
                fullText="OpenAI has launched GPT-5, their latest model...",
                publishedAt=datetime.now(timezone.utc),
                mentionedEntities=["OpenAI", "GPT-5"],
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert len(news.content.mentionedEntities) == 2

    def test_news_empty_entities(self):
        """Mentioned entities can be empty."""
        news = News(
            source=Source(name="Test", url="https://example.com"),
            content=NewsContent(
                title="Generic AI News",
                fullText="Some article content here.",
                publishedAt=datetime.now(timezone.utc),
                mentionedEntities=[],
            ),
            collectedAt=datetime.now(timezone.utc),
        )
        assert news.content.mentionedEntities == []

    def test_news_rejects_empty_title(self):
        """Title must not be empty."""
        with pytest.raises(ValidationError):
            NewsContent(
                title="",
                fullText="Content",
                publishedAt=datetime.now(timezone.utc),
            )

    def test_news_rejects_empty_fulltext(self):
        """Full text must not be empty."""
        with pytest.raises(ValidationError):
            NewsContent(
                title="Title",
                fullText="",
                publishedAt=datetime.now(timezone.utc),
            )


# ═══════════════════════════════════════════════════════════════
# Entity Mapping Log Tests
# ═══════════════════════════════════════════════════════════════

class TestEntityMappingLogSchema:
    """Tests for the Entity Mapping Log schema."""

    def test_valid_mapping_accepted(self):
        log = EntityMappingLog(
            rawName="Open AI",
            canonicalName="OpenAI",
            method=MappingMethod.EXACT_ALIAS,
            confidence=1.0,
            sourceUrl="https://example.com/openai",
            decision=MappingDecision.ACCEPTED,
        )
        assert log.canonicalName == "OpenAI"
        assert log.confidence == 1.0

    def test_mapping_review_null_canonical(self):
        """Canonical name can be null for REVIEW decisions."""
        log = EntityMappingLog(
            rawName="SomeUnknownCo",
            canonicalName=None,
            method=MappingMethod.FUZZY_MATCH,
            confidence=0.65,
            sourceUrl="https://example.com/unknown",
            decision=MappingDecision.REVIEW,
        )
        assert log.canonicalName is None
        assert log.decision == MappingDecision.REVIEW

    def test_mapping_rejects_confidence_out_of_range(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            EntityMappingLog(
                rawName="Test",
                method=MappingMethod.NORMALIZATION,
                confidence=1.5,
                sourceUrl="https://example.com",
                decision=MappingDecision.ACCEPTED,
            )

    def test_mapping_rejects_negative_confidence(self):
        with pytest.raises(ValidationError):
            EntityMappingLog(
                rawName="Test",
                method=MappingMethod.NORMALIZATION,
                confidence=-0.1,
                sourceUrl="https://example.com",
                decision=MappingDecision.ACCEPTED,
            )


# ═══════════════════════════════════════════════════════════════
# Lineage Event Tests
# ═══════════════════════════════════════════════════════════════

class TestLineageEventSchema:
    """Tests for the Lineage Event schema."""

    def test_valid_lineage_event(self):
        event = LineageEvent(
            raw_document_id=uuid4(),
            extraction_run_id=uuid4(),
            extraction_method=ExtractionMethod.API_STRUCTURED,
            validation_result="PASSED",
        )
        assert event.record_version == 1
        assert event.llm_model_used is None

    def test_lineage_with_llm(self):
        event = LineageEvent(
            raw_document_id=uuid4(),
            extraction_run_id=uuid4(),
            extraction_method=ExtractionMethod.LLM_EXTRACTION,
            llm_model_used="gemini-2.0-flash",
            validation_result="PASSED",
        )
        assert event.llm_model_used == "gemini-2.0-flash"


# ═══════════════════════════════════════════════════════════════
# Data Quality Flag Tests
# ═══════════════════════════════════════════════════════════════

class TestDataQualityFlagSchema:
    """Tests for the Data Quality Flag schema."""

    def test_valid_quality_flag(self):
        flag = DataQualityFlag(
            record_type="STARTUP",
            record_id=uuid4(),
            flag_type=QualityFlagType.DISPUTED_VALUE,
            field_name="employeeCount",
            expected_value="1500",
            actual_value="2000",
            source_url="https://example.com",
            status=QualityStatus.DISPUTED,
            quality_score=45.0,
        )
        assert flag.status == QualityStatus.DISPUTED

    def test_quality_score_range(self):
        """Quality score must be 0-100."""
        with pytest.raises(ValidationError):
            DataQualityFlag(
                record_type="STARTUP",
                record_id=uuid4(),
                flag_type=QualityFlagType.LOW_CONFIDENCE,
                field_name="name",
                quality_score=101.0,
            )


# ═══════════════════════════════════════════════════════════════
# JSON Serialization Tests
# ═══════════════════════════════════════════════════════════════

class TestSerialization:
    """Test JSON serialization round-trips."""

    def test_startup_json_roundtrip(self):
        startup = Startup(
            source=Source(name="Test", url="https://example.com"),
            content=StartupContent(entityName="TestCo"),
            collectedAt=datetime.now(timezone.utc),
        )
        json_str = startup.model_dump_json()
        restored = Startup.model_validate_json(json_str)
        assert restored.content.entityName == "TestCo"

    def test_research_paper_json_roundtrip(self):
        paper = ResearchPaper(
            content=ResearchPaperContent(
                title="Test Paper",
                authors=["Author A"],
                paper_url="https://arxiv.org/abs/2301.00001",
                published_date=datetime.now(timezone.utc),
            ),
        )
        json_str = paper.model_dump_json()
        restored = ResearchPaper.model_validate_json(json_str)
        assert restored.content.title == "Test Paper"
