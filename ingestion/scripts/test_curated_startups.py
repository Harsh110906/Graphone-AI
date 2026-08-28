"""
Test unified startup extraction with organization filtering and multi-directory ingestion.
"""

import re
import sys
from urllib.parse import urlparse
import httpx

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

# Known organization indicators
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
    "ibm", "apple", "amazon", "huggingface", "cohere", "upstage", "togethercomputer"
}

def is_hf_organization(slug: str) -> bool:
    slug_lower = slug.lower().strip()
    if slug_lower in KNOWN_ORGS:
        return True
    if any(slug_lower.endswith(f"-{ind}") or slug_lower.startswith(f"{ind}-") or f"-{ind}-" in slug_lower for ind in ORG_INDICATORS):
        return True
    if any(slug_lower.endswith(ind) for ind in ["ai", "labs", "tech", "org", "research"]):
        return True
    return False

# Test directories
urls = [
    ("https://raw.githubusercontent.com/mahseema/awesome-ai-tools/main/README.md", "Awesome AI Tools"),
    ("https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md", "GenAI Ecosystem"),
    ("https://raw.githubusercontent.com/eugeneyan/open-llms/main/README.md", "Open-LLMs Directory"),
    ("https://raw.githubusercontent.com/Hannibal046/Awesome-LLM/main/README.md", "Awesome LLM"),
    ("https://raw.githubusercontent.com/BradyFU/Awesome-Multimodal-Large-Language-Models/main/README.md", "Multimodal AI"),
    ("https://raw.githubusercontent.com/RUCAIBox/LLMSurvey/main/README.md", "LLM Survey Directory"),
    ("https://raw.githubusercontent.com/promptslab/Awesome-Prompt-Engineering/main/README.md", "Prompt Engineering Hub"),
    ("https://raw.githubusercontent.com/ai-boost/awesome-prompts/main/README.md", "AI Tools Directory")
]

startups = []
seen_domains = set()
seen_names = set()

ignored_domains = {
    "github.com", "twitter.com", "x.com", "arxiv.org", "youtube.com",
    "medium.com", "linkedin.com", "facebook.com", "discord.gg", "discord.com",
    "reddit.com", "t.me", "huggingface.co", "google.com", "apple.com"
}

for url, label in urls:
    try:
        r = httpx.get(url, timeout=10.0)
        lines = r.text.splitlines()
        for line in lines:
            line_str = line.strip()
            # Match markdown links: [Name](URL) - Description OR [Name](URL): Description
            matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', line_str)
            for name, link in matches:
                name_clean = name.strip()
                if len(name_clean) < 2 or len(name_clean) > 50:
                    continue
                if any(x in name_clean.lower() for x in ["paper", "code", "model", "readme", "license", "website", "link", "demo", "click", "here", "http"]):
                    continue
                
                domain = urlparse(link).netloc.lower().replace("www.", "")
                if not domain or domain in ignored_domains:
                    continue
                if domain.endswith(".edu") or domain.endswith(".gov"):
                    continue
                
                norm_name = re.sub(r"[^\w]", "", name_clean.lower())
                if domain not in seen_domains and norm_name not in seen_names:
                    seen_domains.add(domain)
                    seen_names.add(norm_name)
                    startups.append({
                        "name": name_clean,
                        "url": link,
                        "domain": domain,
                        "source": label
                    })
    except Exception as e:
        print(f"Error fetching {url}: {e}")

print(f"Total Unique Startups from Curated Directories: {len(startups)}")

# Sample 20
import random
random.seed(42)
sample = random.sample(startups, min(20, len(startups)))
print("\nSAMPLE OF 20 EXTRACTED REAL STARTUPS:")
print("-" * 75)
for i, s in enumerate(sample, 1):
    print(f"{i:2d}. {s['name']:<25} | domain: {s['domain']:<25} | source: {s['source']}")
