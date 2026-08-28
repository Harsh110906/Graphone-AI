# Source Selection Justifications

This document explains why each data source was selected for GraphOne AI Intelligence Search, noting compliance with official APIs, RSS/sitemaps, scraping feasibility, and rate limits.

---

## 1. Research Papers

### 1.1 arXiv API
- **Endpoint**: `http://export.arxiv.org/api/query` (Atom XML)
- **Why Chosen**:
  - Official, free, open API provided by Cornell University / arXiv.
  - Comprehensive coverage of foundational and applied AI papers (CS.AI, CS.LG, CS.CL, CS.CV, CS.RO).
  - Rich metadata: title, authors, abstract, arXiv ID, submission date, comments.
- **Rate Limit / Etiquette**: Max 3 requests/sec (GraphOne conservatively limits to 1 req/sec).
- **GitHub Integration**: Abstracts and comments frequently link to code repositories; enriched via live GitHub REST API calls.

### 1.2 Papers with Code (PwC)
- **Endpoint**: Official REST API / JSON datasets.
- **Why Chosen**:
  - Direct mapping between research papers, benchmark datasets, evaluation metrics (SOTA tables), and official code repositories.
  - Complements arXiv by providing benchmark evaluation context.
- **Rate Limit / Etiquette**: Polite crawling with 1-2 sec request spacing and local caching.

---

## 2. Code & Repository Intelligence

### 2.1 GitHub REST API
- **Endpoint**: `https://api.github.com/repos/{owner}/{repo}`
- **Why Chosen**:
  - Official API for real-time repository health: star counts, forks, open issues, primary language, and license.
  - Star counts are *never estimated or hallucinated*; they are queried directly and cached with a 24-hour TTL.
- **Rate Limit / Etiquette**:
  - 5,000 req/hour (with `GITHUB_TOKEN`), 60 req/hour (unauthenticated).
  - Exponential backoff and automated circuit breaking when remaining calls drop below 5.

---

## 3. News & Ecosystem Updates (24-Hour Freshness Window)

### 3.1 TechCrunch AI
- **Method**: Official RSS (`https://techcrunch.com/category/artificial-intelligence/feed/`)
- **Why Chosen**: Authoritative venture and product coverage in AI. Standard RSS feed with embedded JSON-LD and `<pubDate>`.

### 3.2 VentureBeat AI
- **Method**: Official RSS (`https://venturebeat.com/category/ai/feed/`)
- **Why Chosen**: Industry-standard enterprise AI news, model launches, and strategic funding rounds.

### 3.3 The Verge AI
- **Method**: Official RSS (`https://www.theverge.com/rss/ai-artificial-intelligence/index.xml`)
- **Why Chosen**: Frontier tech policy, major foundation lab rollouts, and consumer AI impact.

### 3.4 MIT Technology Review
- **Method**: Official RSS (`https://www.technologyreview.com/feed/`)
- **Why Chosen**: Deep technical journalism on AI breakthroughs, governance, and safety.

### 3.5 Ars Technica AI / Tech Lab
- **Method**: Official RSS (`https://feeds.arstechnica.com/arstechnica/technology-lab`)
- **Why Chosen**: Rigorous technical coverage of model architectures, hardware infrastructure, and security.

---

## 4. Jobs & Hiring Signal (24-Hour Freshness Window)

### 4.1 Anthropic Public Job Board API
- **Endpoint**: `https://boards-api.greenhouse.io/v1/boards/anthropic/jobs`
- **Why Chosen**: Official Greenhouse REST API directly published by Anthropic. Provides exact `updated_at` timestamps for safety and research hiring.

### 4.2 Scale AI Public Job Board API
- **Endpoint**: `https://boards-api.greenhouse.io/v1/boards/scaleai/jobs`
- **Why Chosen**: Official Greenhouse REST API for data infrastructure, RLHF, and enterprise AI engineering openings.

### 4.3 Databricks Public Job Board API
- **Endpoint**: `https://boards-api.greenhouse.io/v1/boards/databricks/jobs`
- **Why Chosen**: Official Greenhouse REST API for distributed AI training, MosaicML, and Lakehouse data engineering roles.

### 4.4 Together AI Public Job Board API
- **Endpoint**: `https://boards-api.greenhouse.io/v1/boards/togetherai/jobs`
- **Why Chosen**: Official Greenhouse REST API for open-source AI cloud, inference acceleration, and model deployment jobs.

### 4.5 RemoteOK AI Jobs Feed
- **Endpoint**: `https://remoteok.com/api?tag=ai`
- **Why Chosen**: Official structured JSON feed for remote AI/ML engineering, research, and applied product roles across global startups.

---

### 4.6 Resolved Architecture: `first_published` Precedence for Greenhouse Jobs

> [!IMPORTANT]
> **Resolution of Job Freshness (`first_published` vs. `updated_at`)**:
> - **The Problem with `updated_at` Alone**: Relying solely on `updated_at` misclassifies stale postings that were merely edited, had typo fixes, or were administrative refreshes as "fresh". In our audit, Anthropic had 30 jobs modified in the last 24h, but only 13 were truly newly created openings.
> - **The Implemented Fix**: `src/crawler/job_crawler.py` enforces strict date precedence for all Greenhouse-backed sources:
>   $$\text{content.date} = \text{parse}(\text{first\_published}) \;\;[\text{Fallback: } \text{parse}(\text{updated\_at}) \text{ ONLY if first\_published is null/missing}]$$
> - **Non-Greenhouse Sources**: Lever feeds expose `createdAt` (prioritized) and `updatedAt`. RemoteOK exposes a single canonical `date` representing the initial posting date on the board.
> - **ID Monotonicity**: Greenhouse numeric IDs (e.g., `5406982008` vs `4461450008`) are monotonically increasing integers, providing an additional verification layer for creation recency.

---

---

## 5. Research Papers & Benchmark Repositories

### 5.1 arXiv AI & Machine Learning Preprints API
- **Endpoint**: `http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.CV`
- **Why Chosen**: Authoritative primary archive for AI/ML preprints. Exposes immutable canonical arXiv IDs, author lists, primary category taxonomy, abstracts, and publication timestamps in structured Atom XML format.

### 5.2 Papers with Code (PwC) & Hugging Face Daily Research Archive
- **Endpoints**: `https://paperswithcode.com/latest`, `https://huggingface.co/api/daily_papers`
- **Why Chosen**: Connects research paper preprints with verified open-source GitHub code repositories. Enables automated extraction of official model implementation repositories (e.g. `Dao-AILab/flash-attention`, `FlashML-org/FreeToken`, `tauricresearch/tradingagents`) and live GitHub star metrics without estimation.

---

## 6. Startups, AI Labs & Products

### 6.1 Canonical AI Seed Dataset & Entity Registry
- **Path**: `data/seed_entities.json`
- **Why Chosen**: Curated ground-truth registry of 50 core foundation model labs, AI infrastructure providers, and applied AI startups with verified aliases, official domains, and key personnel.

### 6.2 Curated AI Ecosystem Directory
- **Endpoint**: `https://raw.githubusercontent.com/steven2358/awesome-generative-ai/main/README.md`
- **Why Chosen**: Continuously maintained ecosystem directory cataloging 400+ active generative AI startups, foundation model builders, developer tools, and SaaS products with genuine URLs.

### 6.3 Hugging Face AI Hub & Spaces
- **Endpoints**: `https://huggingface.co/api/models?limit=1000`, `https://huggingface.co/api/spaces?limit=1000`
- **Why Chosen**: Real-time discovery of active AI model organizations (`mistralai`, `deepseek-ai`, `Qwen`, `01-ai`, `tiiuae`) and interactive web applications with verifiable hosting URLs and pricing tiers (Free/Freemium/Enterprise).

### 6.4 Known Limitation & Filter Caveat: Organization vs. Individual Account Classification

> [!NOTE]
> **Startup Organization-vs-Individual Filter Caveat & Known Limitations**:
> - **Mechanism**: To filter out individual hobbyist or researcher accounts on Hugging Face while capturing commercial startups and research institutions, `StartupCrawler` applies a two-tier filter:
>   1. **Canonical Whitelist**: Explicit inclusion of verified foundational AI labs (`mistralai`, `meta-llama`, `deepseek-ai`, `qwen`, `stabilityai`, `eleutherai`, `nousresearch`, `tiiuae`, `cohere`, `allenai`, `bigcode`, `unsloth`, `openbmb`, `vllm-project`, `baai`, `thudm`, `01-ai`, `nexusflow`, `internlm`, `deci`, `writer`, `replicate`, `adept`, `google`, `openai`, `anthropic`, `microsoft`, `nvidia`, `databricks`, `salesforce`, `kyutai`, `black-forest-labs`, `cartesia`, `morph-labs`, `sakanaai`, `liquid-ai`, etc.).
>   2. **Naming-Pattern Heuristics**: Filtering slugs for recognized organizational indicators (`-ai`, `-labs`, `-research`, `-team`, `-org`, `-systems`, `-robotics`, `-compute`, `-intelligence`, `-studio`, `-foundation`, `-institute`, `-llm`, `-nlp`, etc.).
> - **Known Edge Cases**:
>   - *False Positives*: An individual developer who named their personal profile with an organizational suffix (e.g., `john-ai-labs`) may occasionally be classified as an organization.
>   - *False Negatives*: A newly founded stealth startup whose username is a single novel word without organizational keywords (e.g., `acme`) may be omitted from the HF Hub crawl unless ingested via the curated directories.
> - **Mitigation**: Primary entity volume is anchored across curated commercial directories (**AI Collection**, **Awesome AI Tools**, **GenAI Ecosystem**, **Prompt Engineering Hub**) where company domains and commercial listings are independently verified.

