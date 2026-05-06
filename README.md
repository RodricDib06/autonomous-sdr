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
| Testing | pytest |

## Prerequisites

- **Python 3.11+** - Download from python.org
- **Homebrew** (macOS) - `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- **Ollama** - Download from ollama.ai
- **Redis** - For job queue
- **PostgreSQL 18** - For data persistence

## Quick Start (Automated Setup)

```bash
# One command to setup everything and choose what to run
bash scripts/setup_and_run.sh
```

This script:
✓ Checks Python version
✓ Creates virtual environment
✓ Installs dependencies
✓ Validates all services (Redis, PostgreSQL, Ollama)
✓ Initializes database
✓ Opens interactive menu

## Manual Setup

### 1. Install Infrastructure

```bash
# Install and start Redis
brew install redis
brew services start redis

# Install and start PostgreSQL 18
brew install postgresql@18
brew services start postgresql@18

# Verify PostgreSQL is running
psql -U postgres -h localhost -p 5433 -c "SELECT version();"
```

### 2. Create Database and User

```bash
# Connect to PostgreSQL
psql -U postgres -h localhost -p 5433

# Inside psql, run:
CREATE USER sdr_user WITH PASSWORD 'sdrpassword';
CREATE DATABASE sdr_db OWNER sdr_user;
\q
```

Or as a single command:
```bash
psql -U postgres -h localhost -p 5433 postgres << EOF
CREATE USER sdr_user WITH PASSWORD 'sdrpassword';
CREATE DATABASE sdr_db OWNER sdr_user;
EOF
```

### 3. Install and Configure Ollama

```bash
# Install Ollama (download from ollama.ai or use brew)
brew install ollama

# Start Ollama service (in another terminal, or as background)
ollama serve

# In another terminal, pull the Mistral model
ollama pull mistral

# Verify it's working
curl http://localhost:11434/api/tags | grep mistral
```

### 4. Setup Python Environment

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize database (creates tables)
python scripts/init_db.py
```

### 5. Configure Environment Variables

The `.env` file is already configured with defaults:
```bash
DATABASE_URL=postgresql://sdr_user:sdrpassword@localhost:5433/sdr_db
REDIS_URL=redis://localhost:6379
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
APP_ENV=development
ICP_MIN_COMPANY_SIZE=50
ICP_MAX_COMPANY_SIZE=500
ICP_INDUSTRIES=SaaS,Technology,Software,FinTech,DevTools
ICP_MIN_SENIORITY=Manager
```

If you changed any defaults, update `.env` accordingly.

## Running the System

### Option A: Use the Interactive Setup Script (Recommended)

```bash
bash scripts/setup_and_run.sh
```

Follow the menu to:
- Start API server
- Start worker
- Run tests
- Generate test data

### Option B: Manual Terminal-by-Terminal

**Terminal 1 - Background Worker** (processes leads):
```bash
source venv/bin/activate
python app/worker/lead_worker.py
```

You should see:
```
INFO - Worker started. Waiting for jobs...
```

**Terminal 2 - API Server** (receives webhooks):
```bash
source venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     AutonomousSDR ready to accept leads
```

**Terminal 3 - Client Operations** (submit and test):
```bash
source venv/bin/activate

# Submit a test lead
curl -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{"name":"Sarah Chen","email":"sarah.chen@stripe.com","company":"Stripe","source":"web_form"}'

# Response: {"id":"...","name":"Sarah Chen","email":"sarah.chen@stripe.com","company":"Stripe","status":"processing","created_at":"..."}
```

## Testing the Pipeline

### 1. Submit a Single Lead

```bash
LEAD_ID=$(curl -s -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Smith",
    "email": "john.smith@techstartup.io",
    "company": "TechStartup"
  }' | jq -r '.id')

echo "Submitted lead: $LEAD_ID"
```

### 2. Monitor Processing

The worker logs will show:
```
[John Smith] Starting pipeline
[John Smith] Enriched → SaaS, Senior
[John Smith] Analysis → verdict=Hot
[John Smith] Validated → final=Hot confidence=0.92
[John Smith] Pipeline complete ✓
```

### 3. Retrieve Results

```bash
# Get enrichment and verdict for the lead
curl http://localhost:8000/leads/$LEAD_ID | jq '.enrichment, .verdict'
```

### 4. Generate Batch Test Data

```bash
# Generate and submit 100 test leads
python scripts/generate_test_data.py

# Query results
curl http://localhost:8000/leads?limit=10 | jq '.[] | {id, name, status}'
```

## API Endpoints

### Health Check
```bash
GET /health
```

### Submit a Lead
```bash
POST /leads
Content-Type: application/json

{
  "name": "string",
  "email": "user@example.com",
  "company": "string",
  "source": "web_form|linkedin|outbound|etc"  # optional, defaults to "webhook"
}
```

### List Leads
```bash
GET /leads?skip=0&limit=100

# Parameters:
# skip: pagination offset (default: 0)
# limit: results per page (default: 100, max: 1000)
```

### Get Lead Details
```bash
GET /leads/{lead_id}

# Returns:
# - Lead info
# - Enrichment data (job title, seniority, company size, industry, revenue, tech stack, confidence)
# - Verdict (analysis result, validation, BANT scores, final verdict, confidence score)
# - Agent logs
```

## Interactive API Documentation

FastAPI automatically generates interactive docs:

```bash
# Swagger UI
http://localhost:8000/docs

# ReDoc
http://localhost:8000/redoc
```

Click on any endpoint to:
- Read description
- Try it out
- See request/response schemas

## Running Tests

```bash
source venv/bin/activate

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_enrichment.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run only fast tests (no Ollama required)
pytest tests/test_enrichment.py tests/test_analysis_agent.py -v
```

## Architecture

### Agents

1. **EnrichmentAgent**
   - Input: Email, company name
   - Output: Job title, seniority, company size, industry, revenue, tech stack
   - Method: Domain heuristics + database lookup

2. **AnalysisAgent**
   - Input: Enriched lead data
   - Output: BANT scores, ICP match, verdict (Hot/Warm/Cold)
   - Method: Mistral 7B via Ollama

3. **ValidatorAgent**
   - Input: Lead profile + analysis verdict
   - Output: Final verdict with confidence score, consistency check
   - Method: LLM-as-judge via Ollama

### Database Schema

**leads** - Core lead records
**enrichments** - Enrichment results (1+ per lead)
**verdicts** - Analysis and validation results (1+ per lead)
**agent_logs** - Audit trail of agent executions

### Queue & Worker

- **Redis Queue**: FastAPI pushes lead IDs when received
- **Worker**: Polls queue, processes lead through 3-agent pipeline
- **Logging**: Structured logs to console, agent execution logged to database

## Troubleshooting

### "Cannot reach Ollama at http://localhost:11434"
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not, start it
ollama serve

# If mistral is not available, pull it
ollama pull mistral
```

### "Redis connection error"
```bash
# Check Redis is running
redis-cli ping  # Should print PONG

# If not, start it
brew services start redis

# Or start manually
redis-server
```

### "PostgreSQL connection error"
```bash
# Check PostgreSQL is running
psql -U postgres -h localhost -p 5433 -c "SELECT 1"

# If not, start it
brew services start postgresql@18

# Check database exists
psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT count(*) FROM leads;"
```

### "ModuleNotFoundError: No module named 'app'"
```bash
# Make sure you're in the project root and venv is activated
cd ~/autonomous-sdr
source venv/bin/activate
python -c "import app; print('OK')"
```

### Tests failing with "database is locked"
```bash
# Tests use in-memory SQLite by default
# If you see lock errors, rebuild environment
rm -rf .pytest_cache
pytest tests/ -v
```

## Daily Workflow Tips

1. **Keep three terminals open**:
   - Worker (python app/worker/lead_worker.py)
   - API (uvicorn app.main:app --reload)
   - Tests/client (pytest or curl)

2. **Monitor logs**:
   - Worker logs show pipeline progress
   - API logs show request traffic
   - Database logs in `/var/log/postgresql/`

3. **Reload behavior**:
   - API server auto-reloads on code changes (--reload flag)
   - Worker needs manual restart

4. **Test data**:
   - Use real company domains (stripe.com, notion.so) for high-confidence enrichment
   - Use fake domains for testing fallback logic

## Next Steps

- [ ] Add Slack/Email notifications on Hot leads
- [ ] Build analytics dashboard (Metabase/Power BI)
- [ ] Add more enrichment sources (Hunter.io, RocketReach)
- [ ] Deploy to Docker containers
- [ ] Add authentication to API endpoints
- [ ] Implement CRM webhook integration

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review logs in worker and API terminals
3. Check database with: `psql -U sdr_user -h localhost -p 5433 -d sdr_db`
4. Run tests to verify components: `pytest tests/ -v`

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
