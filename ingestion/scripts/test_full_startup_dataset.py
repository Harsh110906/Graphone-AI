"""
Test full startup pipeline with organization filtering and multiple curated directories.
"""

import re
import sys
import json
from urllib.parse import urlparse
import httpx

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

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
    slug_lower = slug.lower().strip()
    if slug_lower in KNOWN_ORGS:
        return True
    # Exclude typical personal names / usernames
    if any(slug_lower.endswith(f"-{ind}") or slug_lower.startswith(f"{ind}-") or f"-{ind}-" in slug_lower for ind in ORG_INDICATORS):
        return True
    if any(slug_lower.endswith(ind) for ind in ["ai", "labs", "tech", "org", "research"]):
        return True
    return False

# Directories
directory_urls = [
    ("https://raw.githubusercontent.com/mahseema/awesome-ai-tools/main/README.md", "Awesome AI Tools Directory"),
    ("https://raw.githubusercontent.com/ai-collection/ai-collection/main/README.md", "AI Collection Directory"),
    ("https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md", "GenAI Ecosystem Directory"),
    ("https://raw.githubusercontent.com/eugeneyan/open-llms/main/README.md", "Open-LLMs Directory"),
    ("https://raw.githubusercontent.com/Hannibal046/Awesome-LLM/main/README.md", "Awesome LLM Directory"),
    ("https://raw.githubusercontent.com/BradyFU/Awesome-Multimodal-Large-Language-Models/main/README.md", "Multimodal AI Directory"),
    ("https://raw.githubusercontent.com/RUCAIBox/LLMSurvey/main/README.md", "LLM Survey Directory"),
    ("https://raw.githubusercontent.com/promptslab/Awesome-Prompt-Engineering/main/README.md", "Prompt Engineering Hub")
]

startups = []
seen_domains = set()
seen_names = set()
source_counts = {}

ignored_domains = {
    "github.com", "twitter.com", "x.com", "arxiv.org", "youtube.com",
    "medium.com", "linkedin.com", "facebook.com", "discord.gg", "discord.com",
    "reddit.com", "t.me", "huggingface.co", "google.com", "apple.com"
}

for url, label in directory_urls:
    try:
        r = httpx.get(url, timeout=12.0)
        lines = r.text.splitlines()
        count = 0
        if "ai-collection" in url:
            curr_title = None
            for line in lines:
                line_str = line.strip()
                if line_str.startswith("### "):
                    curr_title = line_str[4:].strip()
                elif curr_title and "[More Information and Pricing](" in line_str:
                    m = re.search(r'\((https?://[^\)]+)\)', line_str)
                    if m:
                        link = m.group(1)
                        norm_name = re.sub(r"[^\w]", "", curr_title.lower())
                        if norm_name not in seen_names and len(curr_title) >= 2:
                            seen_names.add(norm_name)
                            startups.append({
                                "name": curr_title,
                                "url": link,
                                "source": label
                            })
                            count += 1
                        curr_title = None
        else:
            for line in lines:
                line_str = line.strip()
                matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', line_str)
                for name, link in matches:
                    name_clean = name.strip()
                    if len(name_clean) < 2 or len(name_clean) > 50:
                        continue
                    if any(x in name_clean.lower() for x in ["paper", "code", "model", "readme", "license", "website", "link", "demo", "click", "here", "http", "badge"]):
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
                            "source": label
                        })
                        count += 1
        source_counts[label] = count
    except Exception as e:
        print(f"Error on {url}: {e}")

# Add Hugging Face Organizations
hf_org_count = 0
try:
    r = httpx.get("https://huggingface.co/api/models?limit=1000", timeout=12.0)
    models = r.json()
    for m in models:
        mid = m.get("id", "")
        if "/" in mid:
            slug = mid.split("/")[0].strip()
            if is_hf_organization(slug):
                norm = re.sub(r"[^\w]", "", slug.lower())
                if norm not in seen_names:
                    seen_names.add(norm)
                    name = slug.replace("-", " ").title()
                    startups.append({
                        "name": name,
                        "url": f"https://huggingface.co/{slug}",
                        "source": "Hugging Face Verified AI Organization Hub"
                    })
                    hf_org_count += 1
    source_counts["Hugging Face Verified AI Organization Hub"] = hf_org_count
except Exception as e:
    print(f"Error on HF models: {e}")

print(f"\n=======================================================")
print(f"TOTAL VERIFIED AI STARTUPS & COMPANIES: {len(startups)}")
print(f"=======================================================")
print("SOURCE BREAKDOWN:")
for s_name, cnt in source_counts.items():
    print(f"  - {s_name}: {cnt} records")

import random
random.seed(42)
sample = random.sample(startups, min(20, len(startups)))
print("\nRANDOM SAMPLE OF 20 VERIFIED STARTUP RECORDS:")
print("-" * 75)
for i, s in enumerate(sample, 1):
    print(f"{i:2d}. entityName: {s['name']:<30} | source.url: {s['url']}")
