# AutonomousSDR

A portfolio-grade, multi-agent AI sales development platform. Leads enter from six ingestion channels (including a universal webhook for Zapier / Make.com / Typeform), flow through a **10-node LangGraph state machine** with a live **ReAct research agent**, and exit as hot/warm/cold verdicts — with personalized outreach, meeting bookings, CRM sync, and a self-optimizing BANT scoring loop. Zero paid API keys required to run.

```
6 Ingestion channels            10-node LangGraph Pipeline              Actions
─────────────────────           ──────────────────────────────────      ─────────────────────────────
Website Form                    orchestrate → enrich → research         Hot  → Booking (Cal.com)
Marketing Ads          →        → score_intent → analyse →      →       Warm → Outreach (SMTP / A/B)
Inbound Email                   validate                                Cold → CRM Sync
LinkedIn Signal                 │ conditional routing by verdict        All  → Conversational Agent
Event / Conference              ↓                                            (SMS / LinkedIn / email)
Universal Webhook               PostgreSQL + pgvector + Redis
(Zapier, Make, Typeform)        APScheduler (auto-requeue + metrics)
```

---

## What this demonstrates

| Concept | Implementation |
|---|---|
| **Multi-agent orchestration** | LangGraph `StateGraph` — 10 nodes, conditional routing, pub/sub SSE streaming |
| **ReAct research agent** | Tavily + DuckDuckGo fallback; 3-iteration loop; results injected into LLM context |
| **BANT qualification** | LLM analysis + validator judge; configurable float weights |
| **Self-optimization** | BANT weight rebalancing from conversion outcomes; learning rate 0.3 |
| **A/B testing** | Chi-square significance test; auto-promote winner endpoint |
| **Buyer intent scoring** | 10+ heuristic signal rules; source, seniority, funding, BANT signals |
| **Autonomous operation** | APScheduler: auto-requeues stale leads every 5 min; refreshes Prometheus gauges every 1 min |
| **Webhook ingestion** | 5 channel-specific endpoints + 1 universal endpoint (Zapier/Make/n8n/Typeform) |
| **Webhook secret auth** | HMAC `compare_digest` on every ingest endpoint; open mode for demos |
| **Job status polling** | `GET /ingest/jobs/{id}` — Redis fast-path + DB fallback |
| **Runtime config toggle** | `POST /config/enrichment-provider` switches synthetic/hunter/pdl without restart |
| **Semantic memory** | pgvector HNSW index + embeddings; keyword fallback |
| **Email tracking** | 1×1 pixel open tracking + click redirect |
| **5 enrichment sources** | Synthetic · Hunter.io · People Data Labs · Crunchbase signals |
| **Full auth** | JWT access + refresh tokens; RBAC (admin / manager / rep); API key auth |
| **Prometheus metrics** | Queue depth, node duration histograms, LLM call counters, in-flight gauge |
| **React dashboard** | Live pipeline SSE stream, A/B results, BANT weight chart, lead detail drawer |
| **Production hardening** | Rate limiting (slowapi), security headers middleware, CORS from env var, Alembic migrations |
| **222 tests** | Backend: pytest + mocks. Ingest, auth, A/B, enrichment, graph routing, intent scoring, … |

---

## Stack

| Layer | Tool |
|---|---|
| API | FastAPI 0.136 + slowapi rate limiting |
| Agent framework | LangGraph 0.2 |
| AI inference | Groq llama-3.1-70b (default, free) · Ollama + Mistral 7B · Anthropic Claude |
| Research | Tavily (1k searches/mo free) · DuckDuckGo fallback (no key needed) |
| Scheduler | APScheduler 3.x (AsyncIO, in-process) |
| Queue | Redis |
| Database | PostgreSQL 16 |
| Migrations | Alembic — versioned, autogenerate-ready |
| Config | Pydantic `BaseSettings` — type-validated, env-file aware |
| ORM | SQLAlchemy 2 + Pydantic v2 |
| Logging | structlog — JSON in production, coloured console in dev |
| Metrics | prometheus-client — `/metrics` endpoint for Grafana scraping |
| Frontend | React 18 + TypeScript + Vite + Tailwind + Recharts + TanStack Query |
| Auth | JWT HS256 + bcrypt; API key (SHA-256 prefix auth) |
| Deploy | Docker Compose · Railway (`railway.toml`) · `Makefile` for all commands |

---

## Quick Start (zero paid APIs — Docker Compose)

```bash
git clone https://github.com/RodricDib06/autonomous-sdr.git
cd autonomous-sdr
cp .env.example .env
docker compose up --build
```

- API + docs: `http://localhost:8000/docs`
- Frontend:   `http://localhost:5173`
- Login:      `admin@autonomoussdr.com` / `changeme123`

Everything runs in containers — no local Python, Postgres, or Redis needed.

---

## Local Setup (without Docker)

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Redis
- (Optional) Ollama for local AI inference

### 1. Clone and configure

```bash
git clone https://github.com/RodricDib06/autonomous-sdr.git
cd autonomous-sdr
cp .env.example .env
# Edit .env — defaults work with zero paid APIs
```

Recommended free setup (in `.env`):
```
AI_PROVIDER=groq            # free: 6 000 req/h — sign up at console.groq.com
ENRICHMENT_PROVIDER=synthetic  # heuristic — no API key
```

### 2. Install and migrate

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head          # creates all tables (replaces old migration scripts)
```

### 3. Start services

```bash
# Terminal 1 — API
uvicorn app.main:app --reload --port 8000

# Terminal 2 — LangGraph worker
python -m app.worker.lead_worker

# Terminal 3 — Frontend (optional)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173` — login with `admin@autonomoussdr.com` / `changeme123`.

---

## Optional integrations (all have free tiers or are fully mocked)

| Feature | Env var | Free tier |
|---|---|---|
| Fast AI (recommended) | `GROQ_API_KEY` | 6 000 req/h — no credit card |
| Web research | `TAVILY_API_KEY` | 1 000 searches/mo — no credit card |
| Anthropic Claude | `ANTHROPIC_API_KEY` | $5 credit on sign-up |
| Real enrichment | `HUNTER_API_KEY` | 25 lookups/month |
| People Data Labs | `PDL_API_KEY` | 100 calls/month |
| Funding signals | `CRUNCHBASE_API_KEY` | mock when absent |
| SMS outreach | `TWILIO_*` | $15 trial credit |
| Meeting booking | `CAL_SCHEDULING_URL` | cal.com free tier |
| Slack alerts | `SLACK_WEBHOOK_URL` | free |
| HubSpot CRM | `HUBSPOT_API_KEY` | free CRM tier |
| Webhook security | `WEBHOOK_SECRET` | generate: `make secret` |

### Runtime toggles (no restart required)

```bash
# Switch enrichment provider live
POST /config/enrichment-provider?provider=hunter    # or synthetic, pdl

# Check current provider
GET /config/enrichment-provider
```

---

## Architecture deep-dive

### LangGraph pipeline (`app/agents/graph.py`)

```
orchestrate → enrich → research (ReAct) → score_intent → analyse → validate
                                                                        │
                              ┌─────────────────────────────────────────┤
                              ▼            ▼                ▼            ▼
                           booking      outreach        sync_crm   human_handoff
                         (Hot leads)  (Warm leads)    (Cold + all)
```

Every node publishes `{node, status, duration_ms}` to a Redis pub/sub channel. The frontend subscribes via SSE (`GET /leads/{id}/pipeline/stream`) for live execution visualization.

### ReAct research agent (`app/agents/research_agent.py`)

Runs between enrichment and intent scoring. Up to 3 iterations:
1. `search_web` — Tavily full-text search (DuckDuckGo if no key)
2. `check_funding` — looks for funding round announcements
3. `verify_icp` — checks industry/size signals against ICP config

Results are injected into the analysis LLM prompt. The node is non-critical — any exception returns an empty research dict and the pipeline continues.

### Autonomous scheduler (`app/services/scheduler.py`)

APScheduler runs inside the FastAPI process (no extra container):
- Every **5 minutes**: re-queues any lead stuck in `pending` longer than `AUTO_PROCESS_DELAY_SECONDS`
- Every **1 minute**: refreshes Prometheus `pipeline_queue_size` and `leads_in_flight` gauges

### BANT self-optimization (`app/services/optimization_loop.py`)

Every N leads:
1. Splits leads into `converted` (Hot + booked) vs `lost`
2. Computes mean BANT scores per group
3. Weights dimensions with the largest converted/lost separation higher
4. Blends: `new = old × 0.7 + computed × 0.3`
5. Persists an `OptimizationRun` record — visible in the A/B Tests panel

### A/B email sequences (`app/services/ab_testing.py`)

Two default sequences (Variant A: subject-focused, Variant B: value-led). Chi-square significance test at `n ≥ 30` per variant. "Promote winner" marks the losing sequence inactive.

---

## API reference

```
# Ingestion
POST /ingest/{form|ads|email|linkedin|event}   — channel-specific webhooks
POST /ingest/webhook                           — universal (Zapier/Make/Typeform)
GET  /ingest/jobs/{id}                         — poll pipeline status

# Leads
GET  /leads                                    — list with BANT/verdict filters
GET  /leads/{id}                               — full detail + enrichment + verdict
GET  /leads/{id}/pipeline/stream               — SSE live pipeline events
GET  /leads/{id}/pipeline-trace                — per-lead agent execution log
POST /leads/{id}/outreach                      — trigger outreach sequence
POST /leads/{id}/book                          — send booking link
POST /leads/{id}/chat                          — conversational agent turn
GET  /leads/{id}/intent                        — buyer intent signals
GET  /leads/{id}/conversations                 — conversation threads

# A/B & Optimization
GET  /ab-tests/results                         — variant metrics + significance
POST /ab-tests/{id}/promote                    — promote winning sequence
POST /optimization/run                         — trigger BANT weight rebalance
GET  /optimization/weights                     — current live weights

# Config
GET  /config/enrichment-provider               — current provider
POST /config/enrichment-provider?provider=X    — hot-swap provider (admin)
POST /config/slack                             — set Slack webhook
GET  /health                                   — liveness + worker status
GET  /metrics                                  — Prometheus scrape endpoint

# Analytics
GET  /analytics/powerbi-export                 — flat JSON for Power BI
GET  /analytics/powerbi-export.csv             — CSV download
GET  /analytics/semantic-search?query=...      — pgvector similarity search

# Tracking
GET  /track/open/{email_id}                    — open pixel (1×1 GIF)
GET  /track/click/{email_id}?url=...           — click redirect
```

Full interactive docs: `http://localhost:8000/docs`

---

## Testing

```bash
make test           # 222 tests, all passing
make lint           # ruff check
make fmt            # ruff format
```

Test coverage:
- Auth (register, login, refresh, RBAC, API keys)
- Ingest (webhook secret, all 5 channels, universal webhook field detection, job status)
- Enrichment (synthetic, hunter, deduplication)
- A/B testing (chi-square approximation, event recording, winner promotion)
- Intent scoring (all signal rules, edge cases)
- Graph routing (all conditional edges)
- Export, batch, CSV import, data quality, Slack notifier, outreach agent

---

## Deployment

### Docker Compose (recommended for demos)

```bash
docker compose up --build
```

### Railway (one-command cloud deploy)

```bash
npm install -g @railway/cli
railway login && railway link
railway up            # or: make deploy
```

Set environment variables in the Railway dashboard:
```
DATABASE_URL   (Railway Postgres plugin provides this automatically)
REDIS_URL      (Railway Redis plugin)
SECRET_KEY     (generate with: make secret)
GROQ_API_KEY   (optional — free at console.groq.com)
```

### Manual

1. Postgres 16 with pgvector (Supabase · Railway · Neon all support it)
2. Redis (Railway · Upstash free tier)
3. Two processes: `uvicorn app.main:app` and `python -m app.worker.lead_worker`
4. `alembic upgrade head` before first start

---

## Project structure

```
app/
├── agents/
│   ├── graph.py                 # LangGraph state machine (10 nodes)
│   ├── research_agent.py        # ReAct loop — Tavily + DuckDuckGo tools
│   ├── orchestrator_agent.py    # Deduplication, completeness, priority
│   ├── enrichment_agent.py      # Enrichment dispatch + Crunchbase signals
│   ├── analysis_agent.py        # LLM BANT qualification
│   ├── validator_agent.py       # LLM-as-judge consistency check
│   ├── outreach_agent.py        # A/B sequences + SMTP delivery
│   ├── booking_agent.py         # Cal.com booking link + Slack alert
│   └── conversational_agent.py  # Multi-turn replies (SMS / LinkedIn / email)
├── services/
│   ├── scheduler.py             # APScheduler — auto-requeue + metrics refresh
│   ├── rate_limiter.py          # slowapi limiter instance
│   ├── intent_scoring.py        # Buyer intent heuristics (10+ rules)
│   ├── ab_testing.py            # Chi-square A/B significance test
│   ├── optimization_loop.py     # BANT weight self-optimization
│   ├── embedding_service.py     # pgvector embeddings + semantic search
│   ├── crm_sync.py              # HubSpot / Salesforce / Pipedrive adapters
│   ├── memory_service.py        # Conversation history + LLM summarization
│   └── enrichment/
│       ├── synthetic.py         # Heuristic enrichment (zero API, default)
│       ├── hunter.py            # Hunter.io domain lookup
│       ├── pdl.py               # People Data Labs person API
│       └── crunchbase.py        # Crunchbase funding signals
├── routers/
│   └── ingest.py                # 5 channel webhooks + universal + job status
├── worker/
│   └── lead_worker.py           # LangGraph worker (concurrency + watchdog)
├── logging_config.py            # structlog — JSON prod / coloured dev
├── metrics.py                   # Prometheus counters + histograms
└── main.py                      # FastAPI app, middleware, all REST endpoints

alembic/
├── env.py                       # Alembic environment — reads DATABASE_URL from settings
└── versions/
    └── 0001_initial_schema.py   # Baseline migration (replaces all old migration scripts)

frontend/src/pages/
├── Dashboard.tsx                # KPI cards, pipeline funnel, hot leads feed
├── Pipeline.tsx                 # Graph topology + live SSE stream per lead
├── ABTests.tsx                  # A/B variant comparison + BANT optimization
├── Analytics.tsx                # Outreach funnel, BANT weights, industry breakdown
├── Leads.tsx                    # Lead table with verdict/BANT filters
└── Settings.tsx                 # Slack, SMTP, API key management

tests/                           # 222 tests — pytest + unittest.mock
```

---

## License

MIT
