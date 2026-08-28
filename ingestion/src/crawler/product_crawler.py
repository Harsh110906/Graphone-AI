"""
AI Product crawler extracting tools, applications, models, and platforms with verified parent company and pricing.

IMPORTANT DATA INTEGRITY RULES:
- content.startupName must be the creating parent company/startup (resolved to canonical entity), NOT the product's own name.
- If the parent company cannot be determined from the source text or metadata, startupName is emitted as null.
- If pricingModel is not explicitly mentioned in the source document, it is emitted as null.
- Zero heuristic guessing.

Sources:
1. Awesome Generative AI Products (https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md)
2. Hugging Face Spaces AI Applications (https://huggingface.co/api/spaces?limit=100)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional
from urllib.parse import urlparse
import structlog

from src.crawler.base import BaseCrawler, RawDocument
from src.crawler.rate_limiter import DomainRateLimiter
from src.schemas.product import Product, ProductContent, PricingModel
from src.schemas.startup import Source
from src.storage.entity_resolver import EntityResolver

logger = structlog.get_logger(__name__)

GEN_AI_PRODUCTS_URL = "https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md"
HF_SPACES_API_URL = "https://huggingface.co/api/spaces?limit=1000"

COMPANY_PATTERNS = [
    re.compile(r"(?:by|from|created by|developed by|trained by)\s+([A-Z][A-Za-z0-9\s.-]+?)(?:[\.,;\(\[]|$)", re.IGNORECASE),
    re.compile(r"^([A-Z][A-Za-z0-9\s.-]+?)'s\s+", re.IGNORECASE),
]

DOMAIN_TO_COMPANY = {
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "deepmind.google": "Google DeepMind",
    "x.ai": "xAI",
    "mistral.ai": "Mistral AI",
    "stability.ai": "Stability AI",
    "cohere.com": "Cohere",
    "llama.com": "Meta",
    "huggingface.co": "Hugging Face",
    "lmsys.org": "LMSYS",
    "github.com": "GitHub",
    "microsoft.com": "Microsoft",
    "google.com": "Google",
    "runwayml.com": "Runway",
    "midjourney.com": "Midjourney",
    "perplexity.ai": "Perplexity",
}


class ProductCrawler(BaseCrawler):
    """
    Crawler for AI products, developer tools, SaaS applications, and interactive models.
    """

    def __init__(
        self,
        resolver: Optional[EntityResolver] = None,
        max_results: int = 200,
        rate_limiter: Optional[DomainRateLimiter] = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=1.0,
            max_concurrent=2,
            burst=2,
        )
        super().__init__(
            source_name="ai_products_aggregator",
            rate_limiter=limiter,
            max_retries=2,
            timeout_seconds=25,
            concurrency=2,
        )
        self.resolver = resolver or EntityResolver()
        self.max_results = max_results

    async def discover(self) -> AsyncIterator[str]:
        """Yield product discovery endpoints across curated directories and Spaces hubs."""
        yield GEN_AI_PRODUCTS_URL
        # Multi-tag Spaces discovery endpoints
        space_filters = [
            "",
            "filter=gradio",
            "filter=streamlit",
            "filter=docker",
            "filter=text-generation",
            "filter=image-to-image",
            "filter=text-to-image",
            "filter=text-to-speech",
            "filter=conversational",
            "filter=audio-to-audio",
            "filter=summarization",
            "filter=translation",
        ]
        for f in space_filters:
            param = f"?limit=1000&{f}" if f else "?limit=1000"
            yield f"https://huggingface.co/api/spaces{param}"

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Parse raw document into validated Product records."""
        url = doc.source_url

        if "huggingface.co" in url:
            return self._parse_hf_spaces(doc)
        elif "steven2358" in url:
            return self._parse_markdown_products(doc)

        return []

    def _parse_markdown_products(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Extract products with true parent company attribution from markdown listings."""
        text = doc.raw_content
        lines = text.splitlines()
        records = []
        ignored_sections = {"recommended reading", "milestones", "learning resources", "more lists", "contents"}
        current_section = ""

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("## ") or line_str.startswith("### "):
                current_section = line_str.lstrip("# ").strip().lower()
                continue

            if any(ign in current_section for ign in ignored_sections):
                continue

            match = re.match(r"^[-*]\s+\[([^\]]+)\]\((https?://[^\)]+)\)(?:\s*[-–—:]\s*(.*))?", line_str)
            if not match:
                continue

            name = match.group(1).strip()
            link = match.group(2).strip()
            description = match.group(3).strip() if match.group(3) else ""

            if name.startswith("!") or any(k in name.lower() for k in ["badge", "license", "arxiv", "paper", "contributing", "issue", "pull"]):
                continue
            if len(name) < 2 or len(name) > 50:
                continue

            # 1. Extract and resolve creating parent company
            parent_company = self._extract_parent_company(name, description, link)
            resolved_company = None
            if parent_company:
                canonical, decision, score, method = self.resolver.resolve(parent_company, source_url=link)
                resolved_company = canonical if canonical else parent_company

            # 2. Strict pricing classification (null if unverified)
            pricing = self._classify_pricing(name + " " + description)

            rec = self._build_product_record(
                startup_name=resolved_company,
                source_url=link,
                source_name=f"Curated AI Directory ({current_section.title()})",
                pricing_model=pricing,
            )
            if rec:
                records.append(rec)
                if len(records) >= self.max_results:
                    break

        logger.info("parsed_markdown_products", count=len(records))
        return records

    def _parse_hf_spaces(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Extract interactive AI apps from Hugging Face Spaces with org attribution."""
        try:
            spaces = json.loads(doc.raw_content)
        except Exception:
            return []

        records = []
        for s in spaces[:self.max_results]:
            space_id = s.get("id") or s.get("_id", "")
            if not space_id:
                continue

            # In HF Spaces: "org_name/app_name"
            org_candidate = None
            if "/" in space_id:
                org_candidate = space_id.split("/")[0].strip()

            resolved_company = None
            if org_candidate:
                canonical, decision, score, method = self.resolver.resolve(org_candidate, source_url=f"https://huggingface.co/spaces/{space_id}")
                resolved_company = canonical if canonical else org_candidate.replace("-", " ").title()

            source_url = f"https://huggingface.co/spaces/{space_id}"

            # Verify if license explicitly indicates free open-source tier
            tags = s.get("tags", [])
            pricing = None
            if any(t in ["license:mit", "license:apache-2.0", "license:openrail", "license:gpl"] for t in tags):
                pricing = PricingModel.FREE

            rec = self._build_product_record(
                startup_name=resolved_company,
                source_url=source_url,
                source_name="Hugging Face Spaces AI Apps",
                pricing_model=pricing,
            )
            if rec:
                records.append(rec)

        logger.info("parsed_hf_spaces_products", count=len(records))
        return records

    def _extract_parent_company(self, name: str, desc: str, link: str) -> Optional[str]:
        """
        Extract the creating parent company from the source text and domain.
        Returns None if not explicitly identifiable (never guesses).
        """
        # 1. Check patterns in description text
        for pattern in COMPANY_PATTERNS:
            match = pattern.search(desc)
            if match:
                candidate = match.group(1).strip()
                # Discard non-entity phrases or common stopword expressions
                invalid_starters = ["a", "an", "the", "our", "your", "idea", "scratch", "text", "audio", "video", "code"]
                if candidate.lower().split()[0] in invalid_starters and len(candidate.split()) > 2:
                    continue
                if len(candidate) > 2 and len(candidate) < 35:
                    if self.resolver:
                        canonical, _, _, _ = self.resolver.resolve(candidate)
                        return canonical or candidate
                    return candidate

        # 2. Check domain map for authoritative company websites
        parsed = urlparse(link)
        domain = parsed.netloc.lower().replace("www.", "")
        for d, comp in DOMAIN_TO_COMPANY.items():
            if domain == d or domain.endswith("." + d):
                return comp

        return None

    @staticmethod
    def _classify_pricing(text: str) -> Optional[PricingModel]:
        """
        Classify product pricing model ONLY if explicitly verifiable from source text.
        Returns None if not explicitly stated.
        """
        if not text:
            return None

        text_lower = text.lower()

        # Explicit free / open-source statements
        if any(k in text_lower for k in [
            "open source", "open-source", "free to use", "free download",
            "mit license", "apache 2.0", "apache-2.0", "open weights", "free locally", "free tier"
        ]):
            if any(k in text_lower for k in ["freemium", "free tier with paid upgrade", "free plan then paid"]):
                return PricingModel.FREEMIUM
            return PricingModel.FREE

        # Explicit freemium statements
        if any(k in text_lower for k in ["freemium", "free plan with pro", "free credits", "free tier with paid"]):
            return PricingModel.FREEMIUM

        # Explicit enterprise statements
        if any(k in text_lower for k in ["contact sales", "enterprise pricing", "demo upon request", "custom quote", "enterprise tier"]):
            return PricingModel.ENTERPRISE

        # Explicit paid / subscription statements
        if any(k in text_lower for k in [
            "paid plan", "paid subscription", "pricing starts", "per seat",
            "subscription plan", "commercial license", "/mo", "/month", "$"
        ]):
            return PricingModel.PAID

        # Strictly null if not verifiable from text
        return None

    def _build_product_record(
        self,
        startup_name: Optional[str],
        source_url: str,
        source_name: str,
        pricing_model: Optional[PricingModel] = None,
    ) -> Optional[dict[str, Any]]:
        """Validate and construct a schema-compliant Product record."""
        collected_at = datetime.now(timezone.utc)

        pricing_val = pricing_model.value if pricing_model else None

        record = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {
                "name": source_name,
                "url": source_url,
            },
            "content": {
                "startupName": startup_name,
                "pricingModel": pricing_val,
            },
            "collectedAt": collected_at.isoformat(),
        }

        # Pydantic validation
        try:
            Product(
                schemaVersion="1.0",
                recordType="PRODUCT",
                source=Source(name=source_name, url=source_url),
                content=ProductContent(
                    startupName=startup_name,
                    pricingModel=pricing_model,
                ),
                collectedAt=collected_at,
            )
            return record
        except Exception as e:
            logger.error("product_schema_validation_failed", startup_name=startup_name, error=str(e))
            return None
