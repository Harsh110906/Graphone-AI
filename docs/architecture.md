# GraphOne AI Intelligence Search — System Architecture Specification

**Document Version:** 1.0  
**Target Submission Artifact:** `architecture.pdf` (Max 3 Pages)  
**Authors:** Senior Staff Systems & Data Architect  
**Classification:** Production Engineering Blueprint  

---

## 1. Scale Strategy (500k+ Records)

GraphOne is engineered to scale from initial seed ingestion to **500,000+ records** without structural codebase refactoring. Scaling is achieved purely by increasing horizontal worker capacity and queue partition concurrency.

```
                  ┌────────────────────────────────────────┐
                  │          SCHEDULER & DISCOVERY         │
                  └───────────────────┬────────────────────┘
                                      │
                         [Redis Streams / Queue]
                         (Topic: ingestion-jobs)
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
  ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
  │ Worker Node 1 │           │ Worker Node 2 │           │ Worker Node N │
  │ (Stateless)   │           │ (Stateless)   │           │ (Stateless)   │
  └───────┬───────┘           └───────┬───────┘           └───────┬───────┘
          │                           │                           │
          └───────────────────────────┼───────────────────────────┘
                                      ▼
                        PostgreSQL (Neon) + pgvector
                    (Atomic Claim: ON CONFLICT DO NOTHING)
```

### 1.1 Stateless Crawler Workers & Queue Coordination
- **Queue Layer**: Ingestion tasks are published to **Redis Streams** with consumer groups (`crawler-workers`).
- **Atomic Claim Semantics**: Distributed worker nodes claim URLs atomically using:
  ```sql
  INSERT INTO crawl_runs (id, source_id, status, started_at)
  VALUES ($1, $2, 'RUNNING', NOW())
  ON CONFLICT (source_id, started_at) DO NOTHING;
  ```
- **Idempotent Pre-Storage Ingestion**: Every entity carries unique deterministic constraints (`news_articles.canonical_url`, `jobs.canonical_url`, `research_papers.arxiv_id`, `startups(normalized_name, official_domain)`). Race conditions across distributed workers are resolved at the database engine level via `ON CONFLICT (canonical_key) DO NOTHING` or `DO UPDATE` (version bumping).

### 1.2 Object Storage Offloading
- Raw HTML/XML payloads and intermediate extraction payloads are streamed directly to **Cloudflare R2** (S3-compatible, zero egress fees), storing only the content hash and R2 URI in PostgreSQL. This prevents table bloat and preserves transactional performance at 500k+ scale.

---

## 2. 413 & 429 Resiliency Engine

GraphOne implements deterministic, zero-data-loss resiliency for Large Language Model extraction and crawler throttling.

```
RAW HTML ──► Boilerplate Removal (readability) ──► Token Count (tiktoken)
                                                           │
                                             ┌─────────────┴─────────────┐
                                             ▼                           ▼
                                    Tokens <= 8,000             Tokens > 8,000
                                             │                           │
                                      Direct LLM Call            Semantic Chunker
                                             │                   (Preserve H1-H3,
                                             │                    entities, dates)
                                             │                           │
                                             │                   Per-Chunk Extract
                                             │                           │
                                             │                   Deterministic Merge
                                             │                           │
                                             └─────────────┬─────────────┘
                                                           ▼
                                               Pydantic Schema Validation
                                               (Strict extra="forbid")
```

### 2.1 Payload Too Large (413) Handling
1. **Sanitization**: Strips scripts, styles, SVGs, and navigation boilerplate using `readability-lxml`.
2. **Token Estimation**: Counts tokens with `tiktoken` (cl100k_base).
3. **Semantic Chunking**: If content exceeds the provider context ceiling (e.g. 8,192 tokens):
   - Preserves document header, metadata block, and main headings (H1–H3).
   - Chunks body by paragraphs, ensuring entity-bearing and numerical sentences are never split.
   - Extracts structured entities per chunk using targeted prompts with strict `null` defaults.
   - Merges chunk outputs deterministically and validates against Pydantic models.

### 2.2 Rate Limit (429) Handling & Multi-Tier Fallback Chain
- **Provider Priority**: `Gemini 2.0 Flash` (Tier 1) $\rightarrow$ `Groq Llama 3.3 70B` (Tier 2) $\rightarrow$ `DeepSeek-V3` (Tier 3).
- **Exponential Backoff with Full Jitter**:
  $$\text{Delay} = \min\left(\text{max\_delay}, \text{base} \times 2^{\text{attempt}}\right) + \text{Uniform}(0, \text{jitter})$$
- **Retry-After Compliance**: HTTP `Retry-After` headers override calculated backoff if longer.
- **Dead-Letter Queue (DLQ)**: After 3 exhausted attempts across all fallback providers, the failed raw document is routed to the DLQ (`data_quality_flags` with `status: PENDING_REVIEW`) for automated alerting and audit.

---

## 3. Freshness & Deduplication Across Distributed Nodes

```
Incoming Record ──► 1. Exact Key Check (URL / arXiv ID / Domain) ──► Duplicate? ──► REJECT
                            │ (No match)
                            ▼
                    2. Normalized Key Check (Unicode, Case, Legal) ──► Duplicate? ──► REJECT
                            │ (No match)
                            ▼
                    3. Blocked Fuzzy Match (RapidFuzz Jaro-Winkler) ──► Similarity >= 0.90 ──► REJECT
                            │ (No match)
                            ▼
                    4. 24-Hour Freshness Waterfall ───────────────► Stale / No Date? ──► REJECT
                            │ (Passed)
                            ▼
                    REGISTER & STORE FACT
```

### 3.1 Three-Tier Deduplication Pipeline
1. **Tier 1 (Exact Key)**: O(1) hash check on canonical URL, arXiv ID, or official domain.
2. **Tier 2 (Normalized Key)**: Strips unicode accents (NFKD), punctuation, whitespace, and legal entities (`Inc.`, `Ltd.`, `PBC`, `GmbH`).
3. **Tier 3 (Blocked Fuzzy Match)**: Blocks records by prefix and entity type (`STARTUP:op`, `JOB:en`). Runs RapidFuzz Jaro-Winkler **strictly within blocks** (similarity threshold $\ge 0.90$). Avoids $O(n^2)$ complexity while catching variations like *"OpenAI"* vs *"Open AI"*.

### 3.2 24-Hour Freshness Waterfall
Every News and Job record is evaluated against a strict timestamp waterfall:
$$\text{JSON-LD} \rightarrow \text{OpenGraph/Meta} \rightarrow \langle\text{time datetime}\rangle \rightarrow \text{Relative Text} \rightarrow \text{RSS Timestamp}$$
**Hard Rule**: If no timestamp within $T - 24\text{ hours}$ can be extracted with confidence, the record is **rejected** — freshness is never assumed.

---

## 4. Storage & Database Architecture Justification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       POSTGRESQL 16 (NEON SERVERLESS)                       │
├───────────────────────────────┬─────────────────────────────┬───────────────┤
│       RELATIONAL TABLES       │     PGVECTOR EXTENSION      │     GRAPH     │
│   (Startups, Jobs, Papers,    │     (1536-dim embeddings,   │ (Relationships│
│     Lineage, Data Quality)    │       HNSW cosine index)    │   & Aliases)  │
└───────────────────────────────┴─────────────────────────────┴───────────────┘
```

### 4.1 Why Unified PostgreSQL (Relational + Vector + Graph)
1. **Elimination of Dual-Write Sync Lag**: Splitting storage across Pinecone/Neo4j/PostgreSQL creates distributed consistency bugs and failure modes. A single PostgreSQL database with `pgvector` guarantees ACID atomicity across relational metadata, vector embeddings, and entity relationships in a single transaction.
2. **Hybrid Search in One Query**: Full-text lexical search (`tsvector` + GIN) and semantic search (`pgvector` cosine similarity) are fused in a single SQL query using Reciprocal Rank Fusion (RRF).
3. **Graph Relations via Adjacency Tables**: Company $\rightarrow$ Product $\rightarrow$ Job $\rightarrow$ News linkages are indexed via foreign keys and indexed relationship tables (`entity_relationships`), providing sub-millisecond graph traversals without Neo4j licensing overhead.
4. **Data Lineage Traceability**: Every entity record maintains foreign keys to `raw_documents` and `lineage_events`, fulfilling zero-tolerance auditability.

---

## 5. Data Quality Scoring & Corroboration Framework

GraphOne computes a transparent, composite Data Quality Score (0–100) for every ingested record:
$$\text{DQS} = 0.30 \cdot S_{\text{reliability}} + 0.25 \cdot S_{\text{corroboration}} + 0.25 \cdot S_{\text{freshness}} + 0.20 \cdot S_{\text{confidence}} - P_{\text{dispute}}$$

### 5.1 Corroboration Scoring Tiers
- **Multi-Source Corroborated ($S_{\text{corrob}} = 100.0$)**: The entity or field has been observed and verified across $\ge 2$ independent sources (e.g. Curated AI Directory + Hugging Face Model Card agreement).
- **Authoritative Primary Registry Single-Source ($S_{\text{corrob}} = 80.0$)**: Records sourced directly from official primary API endpoints with cryptographic or institutional authority (arXiv official API, Greenhouse direct board API, Hugging Face official model hub). These are authoritative but single-source, hence appropriately scored at 80 rather than the multi-source 100.
- **Curated Web / Directory Single-Source ($S_{\text{corrob}} = 70.0$)**: Single-source records from high-quality curated directories without missing fields.
- **Uncorroborated / Missing Optional Fields ($S_{\text{corrob}} = 50.0$)**: Single-source records with missing optional attributes.
- **Disputed Value Penalty ($P_{\text{dispute}} = -25.0$)**: When two independent sources report conflicting values (e.g. `"FREE"` vs `"PAID"` for Cursor), both values are retained with citations, a `DataQualityFlag(flag_type="disputed_value")` is recorded, and a 25-point penalty is subtracted.

---

## 6. PDF Generation Instructions for Submission

To compile this architectural specification into `architecture.pdf` (max 3 pages) for submission:
```bash
# Compile via md-to-pdf or Chrome headless print:
npx -y md-to-pdf docs/architecture.md --pdf-options '{"format": "A4", "margin": "12mm"}'
```
