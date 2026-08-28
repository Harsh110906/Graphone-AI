# GraphOne AI Intelligence Search

> **Production-grade AI Intelligence Search Platform for the global AI/venture ecosystem.**
> Search startups, products, research papers, GitHub repos, jobs, and news — with every result verified, source-linked, and freshness-filtered.

---

## Architecture Overview

GraphOne is structurally separated into two layers:

### Layer 1: Ingestion & Verification Engine (`ingestion/`)
- **Sources**: Real-time APIs (arXiv, Papers with Code, GitHub), curated directories, RSS feeds, and Playwright-rendered web sources.
- **Deduplication**: 3-tier pre-storage dedup (exact key -> normalized key -> blocked fuzzy matching via RapidFuzz Jaro-Winkler).
- **Date Waterfall**: JSON-LD -> OpenGraph/meta -> `<time datetime>` -> relative text parsing -> RSS fallback. Hard 24h freshness filter for news & jobs; dateless records are rejected.
- **LLM Extraction**: Multi-tier fallback chain (Gemini Flash -> Groq Llama 3 -> DeepSeek) with semantic chunking for 413 handling and exponential backoff with jitter for 429 rate limits.
- **Entity Resolution**: Deterministic resolution pipeline (exact alias -> normalized -> blocked fuzzy -> context match -> manual review queue). Seeded with ~50 canonical AI entities.
- **Cross-Source Verification & Data Quality**: Corroboration of high-value facts; automated Data Quality Score (0-100); full data lineage (`raw_document_id` -> `extraction_run_id` -> `llm_model_used` -> `validation_result`).
- **Anti-Bot Fallback Chain**: Direct HTTP -> official API/RSS -> Playwright Async rendering -> skip-and-log (zero CAPTCHA bypassing).
- **Export**: Idempotent Google Sheets exporter (`gspread`) writing to 6 designated tabs with CSV dry-run fallback.

### Layer 2: Search Product (`web/`)
- **Framework**: Next.js 16 (App Router) + TypeScript + Tailwind CSS + Prisma ORM.
- **Auth & Quotas**: Clerk authentication (Email, Google, GitHub) + server-side quota enforcement (signed cookie + hashed-IP fallback + Redis counter for anonymous users; tiered quotas for authenticated users).
- **Search**: PostgreSQL hybrid search (tsvector/GIN lexical + pgvector semantic) with natural-language query decomposition.

---

## Directory Structure

```
graphone-ai/
├── README.md
├── .env.example
├── docker-compose.yml              # PostgreSQL (with pgvector) + Redis
│
├── ingestion/                       # LAYER 1: Python Ingestion Engine
│   ├── pyproject.toml
│   ├── src/
│   │   ├── config.py               # Validated env config (pydantic-settings)
│   │   ├── schemas/                # Strict Pydantic entity schemas
│   │   ├── crawler/                # BaseCrawler, arXiv, BrowserCrawler, etc.
│   │   ├── storage/                # DeduplicationEngine, DB models
│   │   ├── export/                 # Google Sheets & CSV export
│   │   └── observability/          # Structured JSON logging
│   ├── scripts/
│   │   ├── run_pipeline.py         # Ingestion CLI
│   │   └── run_sheets_export.py    # Export CLI
│   ├── tests/                      # Full pytest test suite
│   └── data/
│       └── seed_entities.json      # 50 canonical AI entities + aliases
│
├── web/                            # LAYER 2: Next.js Search Product
│   ├── prisma/
│   │   └── schema.prisma           # 20+ tables data model
│   ├── src/
│   └── package.json
│
└── docs/
    ├── architecture.md             # Submission architecture doc
    └── source_justifications.md    # Source selection rationale
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (for local PostgreSQL + pgvector and Redis)

### 1. Environment Setup
Copy `.env.example` to `.env` in the root (and in `ingestion/` if running standalone):
```bash
cp .env.example .env
```

### 2. Start Local Infrastructure
```bash
docker-compose up -d
```
This starts:
- PostgreSQL 16 on port 5432 with `pgvector` extension enabled
- Redis 7 on port 6379

### 3. Run Ingestion Tests & Pipeline (Layer 1)
```bash
cd ingestion
pip install -e .
# Install dependencies:
pip install pydantic pydantic-settings httpx rapidfuzz structlog python-dotenv beautifulsoup4 lxml feedparser pytest pytest-asyncio respx gspread google-auth

# Run complete unit test suite (150 tests)
pytest -v

# Run the full scale-up ingestion & verification pipeline
python scripts/run_scale_and_quality.py

# Push live to Google Sheets
python scripts/run_sheets_export.py --input output/pipeline_results.json
```

### 4. Run Web Application (Layer 2)
```bash
cd ../web
npm install
npx prisma generate
npm run dev
```

---

## Live Google Sheets Dataset

The production ingestion pipeline has populated the public Google Spreadsheet across all 6 required tabs:

📊 **[Public Google Sheets Dataset Link](https://docs.google.com/spreadsheets/d/1U5PnFQMsGVCvlSv1mEBkY-BcNYe6s3dzpOQPTzzfZ8c/edit?usp=sharing)**

| Tab | Live Ingested Rows | Minimum Required | Status | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Startups** | **1,413** | 1,000 | **PASS** | Verified AI companies and research labs (personal accounts excluded) |
| **Products** | **1,248** | 1,000 | **PASS** | Interactive AI applications with verified parent company attribution |
| **Research Papers** | **1,218** | 1,000 | **PASS** | arXiv AI/ML preprints with live GitHub star metrics |
| **Jobs** | **23** | 5 per board | **PASS** | 24-hour fresh openings with `first_published` timestamp precedence |
| **News** | **12** | 5 per source | **PASS** | 24-hour fresh articles verified via JSON-LD date waterfall |
| **Entity Mapping Log** | **5,012** | Full audit | **PASS** | Complete resolution audit trail for every entity decision |

---

## Data Integrity & Quality Guarantees

1. **Zero Hallucination**: Every stored record originates from an audited HTTP request with an immutable `source_url`. Missing fields are strictly stored as `null`.
2. **Date Extraction Waterfall**: News and jobs are rejected if a verified publication timestamp within 24 hours cannot be extracted from structured metadata or text.
3. **Traceability**: All extracted facts carry an end-to-end lineage record (`raw_document_id`, `extraction_run_id`, `extraction_method`, `llm_model_used`).
4. **Anti-Bot Compliance**: Playwright Async is used with realistic headers, randomized pacing, and low concurrency. CAPTCHAs are detected and logged as skip events — never bypassed.
5. **Quality Scoring**: Every fact carries a composite Data Quality Score (0–100) based on source reliability, cross-source corroboration, freshness, and extraction confidence.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
