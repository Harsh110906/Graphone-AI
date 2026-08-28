import httpx, re
from urllib.parse import urlparse

url = 'https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md'
res = httpx.get(url)

COMPANY_PATTERNS = [
    re.compile(r"(?:by|from|created by|developed by|trained by)\s+([A-Z][A-Za-z0-9\s.-]+?)(?:[\.,;\(\[]|$)", re.IGNORECASE),
    re.compile(r"^([A-Z][A-Za-z0-9\s.-]+?)'s\s+", re.IGNORECASE),
]

def extract_company(name, desc, link):
    # 1. Pattern from description
    for pat in COMPANY_PATTERNS:
        m = pat.search(desc)
        if m:
            cand = m.group(1).strip()
            cand = re.sub(r'^(the|an|a)\s+', '', cand, flags=re.IGNORECASE)
            if len(cand) > 1 and len(cand) < 35 and not any(k in cand.lower() for k in ['fine tuning', 'using', 'based', 'large', 'open source', 'trained', 'different']):
                return cand
    # 2. Match known company domains
    domain = urlparse(link).netloc.lower().replace('www.', '')
    domain_map = {
        'openai.com': 'OpenAI',
        'anthropic.com': 'Anthropic',
        'deepmind.google': 'Google DeepMind',
        'x.ai': 'xAI',
        'mistral.ai': 'Mistral AI',
        'stability.ai': 'Stability AI',
        'cohere.com': 'Cohere',
        'llama.com': 'Meta',
        'huggingface.co': 'Hugging Face',
        'lmsys.org': 'LMSYS',
        'github.com': 'GitHub',
        'microsoft.com': 'Microsoft',
        'google.com': 'Google',
    }
    for d, comp in domain_map.items():
        if domain == d or domain.endswith('.' + d):
            return comp
    return None

entities = []
for line in res.text.splitlines():
    m = re.match(r"^[-*]\s+\[([^\]]+)\]\((https?://[^\)]+)\)(?:\s*[-–—:]\s*(.*))?", line.strip())
    if m:
        name, link, desc = m.group(1).strip(), m.group(2).strip(), (m.group(3) or '').strip()
        comp = extract_company(name, desc, link)
        if not name.startswith('!') and len(name) < 30:
            entities.append((name, comp, desc[:40]))

print(f"Total tested: {len(entities)}")
for name, comp, desc in entities[:20]:
    print(f"{name:20s} -> Company: {str(comp):20s} | Desc: {desc}")
