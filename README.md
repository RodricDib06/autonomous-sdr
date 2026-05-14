# AutonomousSDR

A portfolio-grade, multi-agent AI sales development platform. Leads enter from five ingestion channels, flow through a **LangGraph state machine** of specialized agents, and exit as hot/warm/cold verdicts with personalized outreach sequences, meeting bookings, and CRM sync — all with zero paid API keys required.

```
5 Ingestion channels          LangGraph State Machine               Actions
──────────────────            ──────────────────────────────────    ─────────────────────────────
Website Form                  Orchestrate → Enrich                  Hot  → Booking Agent (Cal.com)
Marketing Ads          →      → Intent Score → Analyse →    →       Warm → Outreach Agent (SMTP)
Inbound Email                 Validate                              Cold → CRM Sync
LinkedIn Signal               │                                          (HubSpot / Salesforce / Pipedrive)
Event / Conference            ↓ Conditional routing by verdict      All  → Conversational Agent
                         PostgreSQL + pgvector                           (SMS via Twilio / LinkedIn via Unipile)
```

## What this demonstrates

| Concept | Implementation |
|---|---|
| **Multi-agent orchestration** | LangGraph `StateGraph` with conditional edges; 9 agent nodes |
| **BANT qualification** | Analysis + Validator agents with float scores, configurable weights |
| **Self-optimization** | Weight rebalancing loop from conversion outcomes (learning rate 0.3) |
| **A/B testing** | Chi-square significance test on outreach sequences; auto-promote winner |
| **Buyer intent scoring** | Heuristic signal rules (source, enrichment, BANT, funding signals) |
| **Semantic memory** | pgvector HNSW index + Ollama embeddings; keyword fallback |
| **Email tracking** | 1×1 pixel open tracking + click redirect |
| **5 enrichment sources** | Synthetic (default) · Hunter.io · People Data Labs · Crunchbase signals |
| **5 ingestion channels** | REST webhooks with deduplication |
| **Full auth** | JWT access + refresh tokens, role-based access (admin/manager/rep) |
| **React dashboard** | Pipeline traces, A/B test results, outreach funnel, BANT weight chart |

---

## Stack

| Layer | Tool |
|---|---|
| API | FastAPI 0.115 |
| Agent framework | LangGraph 1.2 |
| AI inference | Ollama + Mistral 7B (default, free) · Anthropic Claude (optional) |
| Embeddings | Ollama `nomic-embed-text` (768-dim) |
| Vector search | pgvector HNSW (cosine similarity) |
| Queue | Redis |
| Database | PostgreSQL 13+ |
| ORM | SQLAlchemy 2 + Pydantic v2 |
| Frontend | React 18 + TypeScript + Vite + Tailwind + Recharts |
| Auth | JWT (HS256) + bcrypt |
| Tests | pytest (137 tests) |

---

## 5-Minute Setup (zero paid APIs)

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) — runs the LLM locally
- PostgreSQL 13+
- Redis

### 1. Clone and configure

```bash
git clone https://github.com/RodricDib06/autonomous-sdr.git
cd autonomous-sdr
cp .env.example .env
```

The defaults in `.env` require **no changes** for local dev:
```
AI_PROVIDER=ollama          # free, local — no API key needed
ENRICHMENT_PROVIDER=synthetic  # heuristic enrichment — no API key needed
```

### 2. Pull the model

```bash
ollama pull mistral          # ~4 GB, one-time
ollama pull nomic-embed-text # for semantic search — optional
```

### 3. Install and initialise

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create tables (run each migration in order — all are idempotent)
python scripts/init_db.py
python scripts/migrate_auth.py
python scripts/migrate_phase2_fields.py
python scripts/migrate_phase3_tables.py
python scripts/migrate_phase4_pgvector.py   # needs pgvector installed — safe to skip
python scripts/migrate_phase5_fields.py     # optional analytics fields
```

> **pgvector optional**: if your Postgres doesn't have the `vector` extension, skip `migrate_phase4_pgvector.py`. Semantic search falls back to keyword matching automatically.

### 4. Start services

```bash
# Terminal 1 — API
uvicorn app.main:app --reload --port 8000

# Terminal 2 — LangGraph worker
python -m app.worker.lead_worker

# Terminal 3 — Frontend (optional)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173` · Login with `admin@autonomoussdr.com` / `changeme123`

---

## Optional integrations (all have free tiers or are fully mocked)

Set in `.env` — the app works without any of these:

| Feature | Env var | Free tier |
|---|---|---|
| Anthropic Claude | `ANTHROPIC_API_KEY` | $5 credit on sign-up |
| Real enrichment | `HUNTER_API_KEY` | 25 lookups/month |
| People Data Labs | `PDL_API_KEY` | 100 calls/month |
| SMS outreach | `TWILIO_*` | $15 trial credit |
| LinkedIn DMs | `UNIPILE_API_KEY` | trial available |
| Email delivery | `SMTP_*` | Gmail free (500/day) |
| Meeting booking | `CAL_SCHEDULING_URL` | cal.com free |
| Slack alerts | `SLACK_WEBHOOK_URL` | free |
| HubSpot CRM | `HUBSPOT_API_KEY` | free tier |
| Crunchbase signals | `CRUNCHBASE_API_KEY` | deterministic mock when absent |

Switch providers with a single env var:
```bash
AI_PROVIDER=claude              # ollama | claude
ENRICHMENT_PROVIDER=hunter      # synthetic | hunter | pdl
```

---

## Architecture deep-dive

### LangGraph state machine (`app/agents/graph.py`)

```
orchestrate ──→ enrich ──→ score_intent ──→ analyse ──→ validate
                                                            │
                        ┌───────────────────────────────────┤
                        ▼               ▼               ▼   ▼
                     booking        outreach         sync_crm  human_handoff
                   (Hot leads)    (Warm leads)      (Cold + all)
```

Routing is purely data-driven: the `validate` node sets `final_verdict` in the shared `LeadState` TypedDict, and `route_after_validate()` reads it to pick the next node. Adding a new agent = adding one function and one edge.

### Buyer intent scoring (`app/services/intent_scoring.py`)

Signals fire when conditions match enrichment data:
- Source priority (LinkedIn signal → 0.20, event → 0.15, website → 0.10, …)
- Seniority ≥ Director → +0.15
- Company size 50–500 → +0.10
- ICP industry match → +0.15
- Recent funding round → +0.20
- BANT-derived signals (hot budget, tight timeline) → up to +0.20

### Self-optimization loop (`app/services/optimization_loop.py`)

Every N leads, the loop:
1. Splits leads into `converted` (Hot, booked) vs `lost`
2. Computes mean BANT scores for each group
3. Assigns higher weights to dimensions with the largest separation
4. Blends: `new = old × 0.7 + computed × 0.3`
5. Persists `OptimizationRun` for the A/B Tests → Optimization History panel

### A/B email sequences (`app/services/ab_testing.py`)

Two default sequences (Variant A: subject-focused, Variant B: value-led). Events are recorded per-email. Once `n ≥ 30` per variant, a chi-square test determines the winner. The "Promote winner" button in the UI marks the losing sequence inactive.

---

## API highlights

```
POST /ingest/{form|ads|email|linkedin|event}  — 5 ingestion webhooks
GET  /leads/{id}/pipeline-trace              — per-lead LangGraph execution trace
GET  /leads/{id}/intent                      — buyer intent signals
GET  /leads/{id}/outreach                    — outreach email schedule
POST /leads/{id}/chat                        — conversational agent turn
GET  /ab-tests/results                       — variant comparison with significance
POST /ab-tests/{id}/promote                  — promote winning sequence
POST /optimization/run                       — trigger BANT weight rebalance
GET  /optimization/weights                   — current live weights
GET  /analytics/powerbi-export               — flat JSON export for Power BI
GET  /analytics/powerbi-export.csv           — CSV version
GET  /analytics/semantic-search?q=...        — pgvector similarity search
GET  /track/open/{email_id}                  — open-tracking pixel (1×1 GIF)
GET  /track/click/{email_id}?url=...         — click redirect + tracking
```

Full interactive docs at `http://localhost:8000/docs`

---

## Running tests

```bash
pytest tests/ -v
# 137 tests, all passing
```

---

## Project structure

```
app/
├── agents/
│   ├── graph.py              # LangGraph state machine (entry point for worker)
│   ├── orchestrator_agent.py # Deduplication, completeness gate, priority scoring
│   ├── enrichment_agent.py   # Enrichment + Crunchbase intent signals
│   ├── analysis_agent.py     # LLM BANT qualification (Ollama / Claude)
│   ├── validator_agent.py    # LLM-as-judge consistency check
│   ├── outreach_agent.py     # A/B sequences + SMTP delivery
│   ├── booking_agent.py      # Cal.com booking link + Slack alert
│   └── conversational_agent.py  # Multi-turn reply (SMS / LinkedIn / mock)
├── services/
│   ├── intent_scoring.py     # Buyer intent heuristics
│   ├── ab_testing.py         # Chi-square A/B significance test
│   ├── optimization_loop.py  # BANT weight self-optimization
│   ├── embedding_service.py  # pgvector embeddings + semantic search
│   ├── crm_sync.py           # HubSpot / Salesforce / Pipedrive adapters
│   ├── memory_service.py     # Conversation history + summarization
│   └── enrichment/
│       ├── synthetic.py      # Heuristic enrichment (zero API, default)
│       ├── hunter.py         # Hunter.io domain lookup
│       ├── pdl.py            # People Data Labs person API
│       └── crunchbase.py     # Crunchbase funding signals
├── routers/
│   └── ingest.py             # 5 ingestion channel webhooks
├── worker/
│   └── lead_worker.py        # LangGraph worker (concurrency + watchdog)
└── main.py                   # FastAPI app + all REST endpoints

frontend/src/
├── pages/
│   ├── Dashboard.tsx         # KPI cards, pipeline funnel, hot leads feed
│   ├── Pipeline.tsx          # LangGraph graph topology + per-lead trace
│   ├── ABTests.tsx           # A/B variant comparison + BANT optimization
│   ├── Analytics.tsx         # Outreach funnel, BANT weights, industry breakdown
│   └── Leads.tsx             # Lead table with verdict/BANT filters
scripts/
├── init_db.py                # Create base tables
├── migrate_phase3_tables.py  # Phase 3: outreach, booking, intent, conversations
└── migrate_phase4_pgvector.py  # Phase 4: vector extension + HNSW index

tests/
└── (137 tests, all passing)
```

---

## Deployment

The app is stateless between the API and worker — both read from the same Postgres + Redis. A minimal production deploy needs only:

1. A Postgres database with pgvector (Supabase / Railway / Neon all support it)
2. A Redis instance (Railway / Upstash free tier)
3. Two Dynos / containers: `uvicorn app.main:app` and `python -m app.worker.lead_worker`
4. Set `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` in environment

For real email delivery, replace the SMTP block with a [SendGrid](https://sendgrid.com) or [Mailgun](https://mailgun.com) adapter — the swap point is `OutreachAgent._send_email()` with production code already commented in.

For production AI, set `AI_PROVIDER=claude` and add `ANTHROPIC_API_KEY`.

---

## License

MIT
