# AutonomousSDR Multi-Agent

A local-first AI lead qualification system. Three specialized agents process inbound sales leads end-to-end — zero paid APIs, zero human involvement.

```
Lead Form → FastAPI Webhook → Redis Queue → Worker
                                                ↓
                                    EnrichmentAgent (domain heuristics)
                                                ↓
                                    AnalysisAgent (Mistral via Ollama)
                                                ↓
                                    ValidatorAgent (LLM-as-judge)
                                                ↓
                                         PostgreSQL
```

## Stack

| Layer | Tool |
|---|---|
| API | FastAPI |
| Queue | Redis |
| AI Inference | Ollama + Mistral 7B |
| Database | PostgreSQL 18 |
| ORM | SQLAlchemy 2 |
| Validation | Pydantic v2 |

## Prerequisites

- Python 3.11+
- Homebrew (macOS)
- Ollama installed and running

## Setup

```bash
# 1. Install and start infrastructure
brew install redis && brew services start redis
brew services start postgresql@18
psql -U <your-user> -p 5433 postgres -c "CREATE USER sdr_user WITH PASSWORD 'sdrpassword';"
psql -U <your-user> -p 5433 postgres -c "CREATE DATABASE sdr_db OWNER sdr_user;"

# 2. Pull Ollama model
ollama pull mistral

# 3. Create virtualenv and install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env  # or edit .env directly
```

## Daily Development Workflow

Terminal 1 — Worker:
```bash
source venv/bin/activate
python -m app.worker.lead_worker
```

Terminal 2 — API server:
```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API docs.

## Demo

Submit a lead:
```bash
curl -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{"name":"Sarah Chen","email":"sarah.chen@stripe.com","company":"Stripe"}'
```

Wait ~10 seconds, then retrieve the result:
```bash
curl http://localhost:8000/leads/<lead-id>
```

Generate 100 test leads:
```bash
python scripts/generate_test_data.py
```

Load analytics views (for Metabase/Power BI):
```bash
psql postgresql://sdr_user:sdrpassword@localhost:5433/sdr_db \
  -f database/analytics_views.sql
```

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v
```

## Architecture

### Agents

**EnrichmentAgent** — Builds a structured lead profile from email domain using rule-based heuristics and a local company database. Strategy Pattern: the provider is behind an abstract interface, swappable with real APIs (Clearbit, PDL).

**AnalysisAgent** — Evaluates the enriched profile against configurable ICP and BANT criteria using Mistral 7B. Returns Hot/Warm/Cold verdict with reasoning and per-dimension BANT scores.

**ValidatorAgent** — LLM-as-judge: a second Mistral call audits the Analysis Agent's decision for logical consistency. Assigns a confidence score (0–1) and can downgrade contradictory verdicts.

### Database Schema

- `leads` — raw webhook input
- `enrichments` — structured profile per lead
- `verdicts` — analysis + validation results
- `agent_logs` — full audit trail of every agent execution

### ICP Configuration

Edit `.env` to tune the Ideal Customer Profile:
```
ICP_MIN_COMPANY_SIZE=50
ICP_MAX_COMPANY_SIZE=500
ICP_INDUSTRIES=SaaS,Technology,Software,FinTech,DevTools
ICP_MIN_SENIORITY=Manager
```
