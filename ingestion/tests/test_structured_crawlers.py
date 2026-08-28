"""
Unit tests for PwcCrawler, StartupCrawler, and ProductCrawler.
"""

import json
from datetime import datetime, timezone
import pytest

from src.crawler.base import RawDocument
from src.crawler.pwc_crawler import PwcCrawler
from src.crawler.startup_crawler import StartupCrawler
from src.crawler.product_crawler import ProductCrawler
from src.schemas.product import PricingModel


class TestPwcCrawler:
    """Test suite for Papers with Code crawler."""

    @pytest.mark.asyncio
    async def test_pwc_html_parsing(self):
        html = """
        <html>
          <body>
            <article>
              <h3>FlashAttention-3: Fast and Accurate Attention with FP8</h3>
              <a href="https://arxiv.org/abs/2407.08608">arXiv</a>
              <a href="https://github.com/Dao-AILab/flash-attention">Code</a>
              <a href="/Dao-AILab">Dao-AILab</a>
            </article>
          </body>
        </html>
        """
        doc = RawDocument(
            source_name="papers_with_code",
            source_url="https://paperswithcode.com/latest",
            raw_content=html,
            http_status=200,
        )

        from src.crawler.github_client import GitHubClient
        client = GitHubClient()
        client._cache["dao-ailab/flash-attention"] = (25000, 9999999999.0)
        crawler = PwcCrawler(github_client=client, max_results=5)
        records = await crawler.parse(doc)

        assert len(records) == 1
        rec = records[0]
        assert rec["recordType"] == "RESEARCH_PAPER"
        assert "FlashAttention" in rec["content"]["title"]
        assert rec["content"]["paper_url"] == "https://arxiv.org/abs/2407.08608"
        assert rec["content"]["github_url"] == "https://github.com/Dao-AILab/flash-attention"


class TestStartupCrawler:
    """Test suite for Startup crawler."""

    @pytest.mark.asyncio
    async def test_startup_markdown_parsing(self):
        md = """
        # Awesome Generative AI Startups
        - [Mistral AI](https://mistral.ai) - Open-weight frontier models
        - [Scale AI](https://scale.com) - Data platform for AI
        - [Invalid Badge](https://img.shields.io/badge) - Badge
        """
        doc = RawDocument(
            source_name="ai_startups_aggregator",
            source_url="https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md",
            raw_content=md,
            http_status=200,
        )

        crawler = StartupCrawler(max_results=10)
        records = await crawler.parse(doc)

        assert len(records) >= 2
        names = [r["content"]["entityName"] for r in records]
        assert "Mistral AI" in names
        assert "Scale AI" in names
        assert "Invalid Badge" not in names


class TestProductCrawler:
    """Test suite for Product crawler."""

    @pytest.mark.asyncio
    async def test_product_markdown_pricing_and_parent_company(self):
        md = """
        ### Models
        - [Llama](https://www.llama.com/) - Meta's open source large language model.
        - [Claude](https://claude.ai/) - Talk to Claude, an AI assistant from Anthropic.
        - [Midjourney](https://midjourney.com) - Freemium image generator with paid plan
        """
        doc = RawDocument(
            source_name="ai_products_aggregator",
            source_url="https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md",
            raw_content=md,
            http_status=200,
        )

        crawler = ProductCrawler(max_results=10)
        records = await crawler.parse(doc)

        assert len(records) == 3
        llama_rec = next(r for r in records if "llama" in r["source"]["url"])
        claude_rec = next(r for r in records if "claude" in r["source"]["url"])
        mj_rec = next(r for r in records if "midjourney" in r["source"]["url"])

        # Verifies parent company extraction + canonicalization
        assert llama_rec["content"]["startupName"] in ["Meta", "Meta AI"]
        assert llama_rec["content"]["pricingModel"] == PricingModel.FREE.value

        assert claude_rec["content"]["startupName"] == "Anthropic"

        assert mj_rec["content"]["startupName"] == "Midjourney"
        assert mj_rec["content"]["pricingModel"] == PricingModel.FREEMIUM.value

    @pytest.mark.asyncio
    async def test_product_unverified_pricing_and_company(self):
        """If source snippet does not explicitly name company or pricing, values MUST be null."""
        md = """
        ### Search Engines
        - [GenericTool](https://custom-domain.xyz/tool) - A simple neural answer engine
        """
        doc = RawDocument(
            source_name="ai_products_aggregator",
            source_url="https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md",
            raw_content=md,
            http_status=200,
        )

        crawler = ProductCrawler(max_results=5)
        records = await crawler.parse(doc)

        assert len(records) == 1
        assert records[0]["content"]["pricingModel"] is None
        assert records[0]["content"]["startupName"] is None
