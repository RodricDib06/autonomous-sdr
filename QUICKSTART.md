# AutonomousSDR - Step-by-Step Running Guide

## ✅ Prerequisites Check

Before starting, verify you have all services running:

```bash
# 1. Check Redis
redis-cli ping
# Expected: PONG

# 2. Check PostgreSQL
psql -U postgres -h localhost -p 5433 -c "SELECT version();"
# Expected: PostgreSQL 18.x...

# 3. Check Ollama
curl http://localhost:11434/api/tags | jq '.'
# Expected: JSON with model list

# 4. Check Mistral model
ollama list | grep mistral
# Expected: mistral:latest or similar
```

If any service is missing, see README.md Prerequisites section.

## 🚀 Quick Start (5 minutes)

### Step 1: Activate Virtual Environment

```bash
cd ~/autonomous-sdr
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### Step 2: Start Worker (Terminal 1)

```bash
source venv/bin/activate
python app/worker/lead_worker.py
```

Expected output:
```
INFO - Worker started. Waiting for jobs...
```

Leave this running.

### Step 3: Start API Server (Terminal 2)

Open a new terminal in the same directory:

```bash
source venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     ✓ Redis connection OK
INFO:     ✓ Ollama connection OK
INFO:     AutonomousSDR ready to accept leads
```

### Step 4: Submit a Test Lead (Terminal 3)

Open a third terminal:

```bash
cd ~/autonomous-sdr
source venv/bin/activate

# Submit a lead
curl -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sarah Chen",
    "email": "sarah.chen@stripe.com",
    "company": "Stripe"
  }'
```

Expected response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Sarah Chen",
  "email": "sarah.chen@stripe.com",
  "company": "Stripe",
  "status": "processing",
  "created_at": "2026-05-02T10:30:00"
}
```

**Save the `id` for the next step**.

### Step 5: Watch Processing in Worker Terminal

You should see in Terminal 1:
```
[Sarah Chen] Starting pipeline
[Sarah Chen] Enriched → FinTech, VP
[Sarah Chen] Analysis → verdict=Hot
[Sarah Chen] Validated → final=Hot confidence=0.95
[Sarah Chen] Pipeline complete ✓
```

This takes 3-10 seconds depending on Ollama response time.

### Step 6: Retrieve Results

In Terminal 3, get the processed lead:

```bash
# Replace with your lead ID from step 4
curl http://localhost:8000/leads/550e8400-e29b-41d4-a716-446655440000 | jq '.'
```

Expected response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Sarah Chen",
  "email": "sarah.chen@stripe.com",
  "company": "Stripe",
  "status": "complete",
  "created_at": "2026-05-02T10:30:00",
  "enrichment": {
    "job_title": "VP of Engineering",
    "seniority": "VP",
    "company_size": "1000-5000",
    "industry": "FinTech",
    "revenue_estimate": "$1B+",
    "tech_stack": ["AWS", "Python", "PostgreSQL"],
    "confidence": 0.85,
    "enrichment_source": "domain_heuristics_v1"
  },
  "verdict": {
    "analysis_verdict": "Hot",
    "final_verdict": "Hot",
    "confidence_score": 0.95,
    "reasoning": "Strong ICP match. VP-level decision maker at a $1B+ FinTech company.",
    "bant_scores": {
      "budget": "High",
      "authority": "High",
      "need": "Medium",
      "timeline": "Unknown"
    },
    "icp_match": true,
    "validated": true,
    "consistency_notes": "Verdict is logically consistent with the enriched profile.",
    "flags": []
  }
}
```

✅ **Success!** The lead has been fully qualified.

## 📊 Test with Multiple Leads

### Generate 100 Test Leads

```bash
# In Terminal 3
python scripts/generate_test_data.py
```

This will:
- Submit 100 random leads from real companies
- Show progress as they're submitted
- Print summary at the end

### Monitor Processing

Watch Terminal 1 (worker) for processing logs.

### View Results

List all processed leads:
```bash
# Get first 10 leads
curl http://localhost:8000/leads?limit=10 | jq '.[] | {id, name, status}'

# Get with pagination
curl http://localhost:8000/leads?skip=0&limit=20

# Count Hot leads (requires jq)
curl http://localhost:8000/leads?limit=1000 | \
  jq '[.[] | select(.verdict.final_verdict == "Hot")] | length'
```

## 🧪 Run Tests

Make sure worker and API are still running, then:

```bash
# In a new terminal
source venv/bin/activate
pytest tests/ -v

# Run specific test file
pytest tests/test_enrichment.py -v

# Run with coverage
pytest tests/ --cov=app
```

Expected results:
```
tests/test_enrichment.py::test_known_domain_returns_valid_output PASSED
tests/test_enrichment.py::test_unknown_domain_returns_valid_output PASSED
tests/test_analysis_agent.py::test_parse_json_clean PASSED
tests/test_validator_agent.py::test_parse_json_clean PASSED
...
======================== 15 passed in 2.34s ========================
```

## 📖 API Documentation

Open in browser:
```bash
# Swagger UI (interactive)
open http://localhost:8000/docs

# ReDoc (documentation)
open http://localhost:8000/redoc

# Health check
curl http://localhost:8000/health
```

## 🔍 Database Inspection

```bash
# Connect to database
psql -U sdr_user -h localhost -p 5433 -d sdr_db

# Inside psql:
\dt                  # List tables
SELECT COUNT(*) FROM leads;
SELECT COUNT(*) FROM verdicts;
SELECT COUNT(*) FROM enrichments;

# View a specific lead with all details
SELECT l.*, e.*, v.* FROM leads l 
LEFT JOIN enrichments e ON l.id = e.lead_id 
LEFT JOIN verdicts v ON l.id = v.lead_id 
WHERE l.id = 'YOUR_LEAD_ID';

\q                   # Exit psql
```

## 🛠️ Makefile Commands

Shortcut commands:

```bash
make setup         # Install deps + init DB
make db-init       # Initialize database
make run-api       # Start API server
make run-worker    # Start worker
make test          # Run tests
make generate-data # Create 100 test leads
make clean         # Remove cache files
make help          # Show all commands
```

## 🐛 Troubleshooting

### Worker shows no logs
- Check if API server is running (Terminal 2)
- Submit a lead and check the queue: `redis-cli LRANGE lead_jobs 0 -1`

### API server crashes on startup
```bash
# Check if port 8000 is in use
lsof -i :8000

# Kill if needed
kill -9 <PID>
```

### "No JSON object found in LLM response"
- Ollama might be slow or unresponsive
- Check Ollama: `curl http://localhost:11434/api/tags`
- Restart Ollama if needed: `killall ollama && ollama serve`

### Database connection errors
```bash
# Verify PostgreSQL
psql -U postgres -h localhost -p 5433 -c "SELECT 1"

# Check password
psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT 1"
```

### "Redis connection error"
```bash
# Verify Redis
redis-cli ping

# Restart if needed
brew services restart redis
```

## 📋 Common Workflows

### Workflow 1: Test a Single Lead

```bash
# Terminal 1: Worker running
# Terminal 2: API running

# Terminal 3: Submit lead
LEAD_ID=$(curl -s -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"test@stripe.com","company":"Stripe"}' | jq -r '.id')

# Watch worker process it (Terminal 1)

# Retrieve results
curl http://localhost:8000/leads/$LEAD_ID | jq '.verdict'
```

### Workflow 2: Batch Testing

```bash
# Terminal 1: Worker
# Terminal 2: API

# Terminal 3: Generate test leads
python scripts/generate_test_data.py

# Wait for processing...
sleep 30

# View results
curl http://localhost:8000/leads?limit=50 | jq '.[] | {name, company, verdict: .verdict.final_verdict}'
```

### Workflow 3: Development

```bash
# Terminal 1: Worker (auto-reloads on code changes)
python app/worker/lead_worker.py

# Terminal 2: API (auto-reloads on code changes)
python -m uvicorn app.main:app --reload

# Terminal 3: Run tests
pytest tests/ -v --tb=short
# or watch with
pytest-watch tests/
```

## ✨ Next Steps

After confirming the system works:

1. **Integrate with your app**: Use the `/leads` POST endpoint
2. **Monitor leads**: Query `/leads?status=complete&limit=100`
3. **Customize ICP**: Edit `.env` for your business rules
4. **Add more enrichment**: Implement additional EnrichmentProvider
5. **Deploy**: Use Docker (see Docker setup in README)

## 📞 Support

If something doesn't work:

1. **Check logs**: Both worker and API print detailed logs
2. **Verify services**: Run prerequisites check above
3. **Test components**: `pytest tests/test_enrichment.py -v`
4. **Check database**: `psql -U sdr_user -h localhost -p 5433 -d sdr_db`
5. **Read README.md**: More detailed troubleshooting

Good luck! 🚀
