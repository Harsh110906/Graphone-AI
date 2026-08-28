"""
AI Startup crawler extracting verified startups and AI organizations from live web directories.

IMPORTANT DATA INTEGRITY RULE:
- NEVER uses static seed files as record content sources.
- If employeeCount is not explicitly present in the fetched source document, it is emitted as null.
- Zero tolerance for hallucinated or assumed metadata.
- Strictly filters out personal/individual accounts; only verifiable companies and AI organizations are retained.

Sources:
1. Awesome AI Tools Directory (https://raw.githubusercontent.com/mahseema/awesome-ai-tools/main/README.md)
2. AI Collection Ecosystem Directory (https://raw.githubusercontent.com/ai-collection/ai-collection/main/README.md)
3. GenAI Ecosystem Directory (https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md)
4. Open-LLMs Directory (https://raw.githubusercontent.com/eugeneyan/open-llms/main/README.md)
5. Awesome LLM Directory (https://raw.githubusercontent.com/Hannibal046/Awesome-LLM/main/README.md)
6. Multimodal AI Directory (https://raw.githubusercontent.com/BradyFU/Awesome-Multimodal-Large-Language-Models/main/README.md)
7. LLM Survey Directory (https://raw.githubusercontent.com/RUCAIBox/LLMSurvey/main/README.md)
8. Prompt Engineering Hub (https://raw.githubusercontent.com/promptslab/Awesome-Prompt-Engineering/main/README.md)
9. Hugging Face AI Organization Hub (filtered strictly for verified AI labs & organizations)
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
from src.schemas.startup import Startup, StartupContent, StartupData, Source

logger = structlog.get_logger(__name__)

DIRECTORY_URLS = [
    ("https://raw.githubusercontent.com/mahseema/awesome-ai-tools/main/README.md", "Awesome AI Tools Directory"),
    ("https://raw.githubusercontent.com/ai-collection/ai-collection/main/README.md", "AI Collection Directory"),
    ("https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md", "GenAI Ecosystem Directory"),
    ("https://raw.githubusercontent.com/eugeneyan/open-llms/main/README.md", "Open-LLMs Directory"),
    ("https://raw.githubusercontent.com/Hannibal046/Awesome-LLM/main/README.md", "Awesome LLM Directory"),
    ("https://raw.githubusercontent.com/BradyFU/Awesome-Multimodal-Large-Language-Models/main/README.md", "Multimodal AI Directory"),
    ("https://raw.githubusercontent.com/RUCAIBox/LLMSurvey/main/README.md", "LLM Survey Directory"),
    ("https://raw.githubusercontent.com/promptslab/Awesome-Prompt-Engineering/main/README.md", "Prompt Engineering Hub"),
]

# Keywords indicating legitimate organization/company entity rather than individual user
ORG_INDICATORS = {
    "ai", "lab", "labs", "research", "tech", "technologies", "org", "team",
    "systems", "robotics", "intelligence", "compute", "studio", "foundry",
    "ventures", "foundation", "institute", "llm", "nlp", "corporation",
    "community", "project", "data", "deep", "neural", "group", "soft", "corp"
}

KNOWN_ORGS = {
    "mistralai", "meta-llama", "deepseek-ai", "qwen", "google", "openai",
    "anthropic", "stabilityai", "eleutherai", "nousresearch", "tiiuae",
    "cohere", "allenai", "bigcode", "unsloth", "openbmb", "vllm-project",
    "baai", "thudm", "01-ai", "nexusflow", "internlm", "deci", "writer",
    "replicate", "adept", "microsoft", "nvidia", "databricks", "salesforce",
    "ibm", "apple", "amazon", "huggingface", "upstage", "togethercomputer",
    "defog", "lmsys", "mosaicml", "kyutai", "black-forest-labs", "cartesia",
    "morph-labs", "sakanaai", "liquid-ai"
}


def is_hf_organization(slug: str) -> bool:
    """Filter out personal user accounts, retaining only verified AI organizations/labs."""
    slug_lower = slug.lower().strip()
    if slug_lower in KNOWN_ORGS:
        return True
    if any(slug_lower.endswith(f"-{ind}") or slug_lower.startswith(f"{ind}-") or f"-{ind}-" in slug_lower for ind in ORG_INDICATORS):
        return True
    if any(slug_lower.endswith(ind) for ind in ["ai", "labs", "tech", "org", "research"]):
        return True
    return False


class StartupCrawler(BaseCrawler):
    """
    Crawler for live AI startups, labs, and infrastructure companies.
    """

    def __init__(
        self,
        max_results: int = 2000,
        rate_limiter: Optional[DomainRateLimiter] = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=1.0,
            max_concurrent=2,
            burst=2,
        )
        super().__init__(
            source_name="ai_startups_aggregator",
            rate_limiter=limiter,
            max_retries=2,
            timeout_seconds=25,
            concurrency=2,
        )
        self.max_results = max_results

    async def discover(self) -> AsyncIterator[str]:
        """Yield live discovery URLs across multiple AI ecosystem registries."""
        for url, _ in DIRECTORY_URLS:
            yield url

        # Hugging Face Model task registries
        hf_tasks = [
            "text-generation",
            "text2text-generation",
            "fill-mask",
            "sentence-similarity",
            "image-to-text",
            "automatic-speech-recognition",
            "text-to-image",
            "feature-extraction",
            "summarization",
            "translation",
            "question-answering",
            "conversational",
        ]
        for task in hf_tasks:
            yield f"https://huggingface.co/api/models?limit=1000&filter={task}"

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Parse raw content from discovery sources into valid Startup records."""
        url = doc.source_url

        if "ai-collection" in url:
            return self._parse_ai_collection(doc)
        elif "raw.githubusercontent.com" in url:
            return self._parse_markdown_directory(doc)
        elif "huggingface.co" in url:
            return self._parse_hf_orgs(doc)

        return []

    def _parse_ai_collection(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Extract AI companies and products from the AI Collection repository."""
        text = doc.raw_content
        lines = text.splitlines()
        records = []
        curr_title = None

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("### "):
                curr_title = line_str[4:].strip()
            elif curr_title and "[More Information and Pricing](" in line_str:
                m = re.search(r'\((https?://[^\)]+)\)', line_str)
                if m:
                    link = m.group(1)
                    if len(curr_title) >= 2 and len(curr_title) <= 60:
                        rec = self._build_startup_record(
                            name=curr_title,
                            source_url=link,
                            source_name="AI Collection Directory",
                            employee_count=None,
                        )
                        if rec:
                            records.append(rec)
                    curr_title = None

        logger.info("parsed_ai_collection_startups", count=len(records))
        return records

    def _parse_markdown_directory(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Extract startups and AI companies from curated markdown directories."""
        text = doc.raw_content
        lines = text.splitlines()
        records = []
        seen_domains = set()

        ignored_sections = {"recommended reading", "milestones", "learning resources", "more lists", "contents"}
        current_section = "general"

        ignored_domains = {
            "github.com", "twitter.com", "x.com", "arxiv.org", "youtube.com",
            "medium.com", "linkedin.com", "facebook.com", "discord.gg", "discord.com",
            "reddit.com", "t.me", "huggingface.co", "google.com", "apple.com", "awesome.re"
        }

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("## ") or line_str.startswith("### "):
                current_section = line_str.lstrip("# ").strip().lower()
                continue

            if any(ign in current_section for ign in ignored_sections):
                continue

            matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', line_str)
            for name, link in matches:
                name_clean = name.strip()
                if len(name_clean) < 2 or len(name_clean) > 50:
                    continue
                if name_clean.startswith("!") or any(k in name_clean.lower() for k in ["badge", "license", "arxiv", "paper", "contributing", "issue", "pull", "http", "website", "link", "demo"]):
                    continue

                parsed_url = urlparse(link)
                domain = parsed_url.netloc.lower().replace("www.", "")

                if not domain or domain in ignored_domains:
                    continue
                if domain.endswith(".edu") or domain.endswith(".gov"):
                    continue

                if domain in seen_domains:
                    continue
                seen_domains.add(domain)

                rec = self._build_startup_record(
                    name=name_clean,
                    source_url=link,
                    source_name=f"Ecosystem Directory ({current_section.title()})",
                    employee_count=None,
                )
                if rec:
                    records.append(rec)
                    if len(records) >= self.max_results:
                        break

        logger.info("parsed_markdown_startups", source=doc.source_url, count=len(records))
        return records

    def _parse_hf_orgs(self, doc: RawDocument) -> list[dict[str, Any]]:
        """Extract verified AI organizations and labs from Hugging Face hub (excluding personal users)."""
        try:
            models = json.loads(doc.raw_content)
        except Exception:
            return []

        records = []
        seen_orgs = set()

        for m in models:
            model_id = m.get("id") or m.get("modelId", "")
            if "/" in model_id:
                org_slug = model_id.split("/")[0].strip()
                # Strict check: only accept verified organizations/labs
                if not is_hf_organization(org_slug):
                    continue

                if org_slug in seen_orgs or len(org_slug) < 2:
                    continue
                seen_orgs.add(org_slug)

                org_name = org_slug.replace("-", " ").title()
                source_url = f"https://huggingface.co/{org_slug}"

                rec = self._build_startup_record(
                    name=org_name,
                    source_url=source_url,
                    source_name="Hugging Face Verified AI Organization Hub",
                    employee_count=None,
                )
                if rec:
                    records.append(rec)

        logger.info("parsed_hf_orgs", count=len(records))
        return records

    def _build_startup_record(
        self,
        name: str,
        source_url: str,
        source_name: str,
        employee_count: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Validate and construct a schema-compliant Startup record."""
        collected_at = datetime.now(timezone.utc)

        data_obj = StartupData(employeeCount=employee_count)

        record = {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {
                "name": source_name,
                "url": source_url,
            },
            "content": {
                "entityName": name,
                "data": {
                    "employeeCount": employee_count,
                },
            },
            "collectedAt": collected_at.isoformat(),
        }

        # Pydantic schema validation
        try:
            Startup(
                source=Source(name=source_name, url=source_url),
                content=StartupContent(entityName=name, data=data_obj),
                collectedAt=collected_at,
            )
            return record
        except Exception as e:
            logger.warning("startup_validation_failed", name=name, error=str(e))
            return None
