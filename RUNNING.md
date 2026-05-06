# AutonomousSDR - COMPLETE SETUP & RUN GUIDE

## Summary of Changes & Additions

### Files Modified
- ✅ `app/main.py` - Added health check, logging, error handling, pagination
- ✅ `app/agents/validator_agent.py` - Completed missing _parse_json method
- ✅ `README.md` - Comprehensive documentation

### Files Created
- ✅ `tests/__init__.py` - Test module initialization
- ✅ `tests/conftest.py` - Pytest fixtures and configuration
- ✅ `scripts/init_db.py` - Database initialization script
- ✅ `scripts/setup_and_run.sh` - Interactive setup and run script
- ✅ `QUICKSTART.md` - Step-by-step running guide
- ✅ `Makefile` - Common command shortcuts
- ✅ `pytest.ini` - Pytest configuration
- ✅ `.env.example` - Configuration template

### Files Already Present & Verified
- ✅ `app/config.py` - Configuration with environment variables
- ✅ `app/database/models.py` - SQLAlchemy ORM models
- ✅ `app/database/connection.py` - Database connection setup
- ✅ `app/database/crud.py` - Database operations
- ✅ `app/agents/base.py` - Base agent class with logging
- ✅ `app/agents/enrichment_agent.py` - Domain heuristics enrichment
- ✅ `app/agents/analysis_agent.py` - Ollama-based analysis
- ✅ `app/services/ollama_client.py` - Ollama integration
- ✅ `app/services/queue_service.py` - Redis queue management
- ✅ `app/services/enrichment/base.py` - Enrichment provider interface
- ✅ `app/services/enrichment/synthetic.py` - Synthetic enrichment
- ✅ `app/schemas/lead.py` - Lead Pydantic models
- ✅ `app/schemas/enrichment.py` - Enrichment validation
- ✅ `app/schemas/verdict.py` - Verdict validation
- ✅ `app/worker/lead_worker.py` - Background job processor
- ✅ `scripts/generate_test_data.py` - Test data generation
- ✅ `data/company_domains.json` - Domain lookup database
- ✅ `requirements.txt` - Python dependencies
- ✅ `.env` - Environment configuration
- ✅ `tests/test_enrichment.py` - Enrichment tests
- ✅ `tests/test_analysis_agent.py` - Analysis tests
- ✅ `tests/test_validator_agent.py` - Validator tests

---

## STEP-BY-STEP RUNNING INSTRUCTIONS

### Phase 1: Prerequisites Setup (One-time)

#### 1.1 Install System Dependencies (macOS with Homebrew)

```bash
# Install Redis
brew install redis
brew services start redis

# Install PostgreSQL 18
brew install postgresql@18
brew services start postgresql@18

# Verify PostgreSQL is running
psql -U postgres -h localhost -p 5433 -c "SELECT version();"
# Output: PostgreSQL 18.x ...
```

#### 1.2 Create Database and User

```bash
# Create user and database in PostgreSQL
psql -U postgres -h localhost -p 5433 postgres << 'EOF'
CREATE USER sdr_user WITH PASSWORD 'sdrpassword';
CREATE DATABASE sdr_db OWNER sdr_user;
EOF

# Verify
psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT 1;"
# Output: ?column?
#          1
```

#### 1.3 Install and Setup Ollama

```bash
# Install Ollama (download from ollama.ai or use brew)
brew install ollama

# In one terminal, start Ollama service
ollama serve

# In another terminal, pull Mistral model
ollama pull mistral

# Verify Mistral is available
ollama list | grep mistral
# Output: mistral:latest      4.1 GB
```

#### 1.4 Setup Python Environment

```bash
# Navigate to project directory
cd ~/autonomous-sdr

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Verify activation (should see (venv) in prompt)
which python

# Install dependencies
pip install -r requirements.txt
```

#### 1.5 Verify All Services

```bash
# Redis
redis-cli ping
# Output: PONG

# PostgreSQL
psql -U postgres -h localhost -p 5433 -c "SELECT 1;"
# Output: ?column? / 1

# Ollama
curl http://localhost:11434/api/tags | jq '.models | length'
# Output: 1 (or more if you have other models)

# Python imports
python -c "from app.config import settings; print('✓ Imports OK')"
# Output: ✓ Imports OK
```

✅ **Prerequisites Complete**

---

### Phase 2: Initialize Application (One-time)

#### 2.1 Initialize Database Tables

```bash
source venv/bin/activate
python scripts/init_db.py
```

Expected output:
```
INFO - ========== AutonomousSDR Database Init ==========
INFO - Creating database tables...
INFO - ✓ Database tables created successfully
INFO - Verifying database connection...
INFO - ✓ Database verified (currently 0 leads)
INFO - ✓ Database is ready
```

#### 2.2 Verify Configuration

```bash
cat .env
```

The `.env` file should have:
```
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

✅ **Application Ready**

---

### Phase 3: Running the System (Every Development Session)

You need **3 terminal windows** running simultaneously.

#### TERMINAL 1: Background Worker

```bash
cd ~/autonomous-sdr
source venv/bin/activate
python app/worker/lead_worker.py
```

Expected startup output:
```
INFO - Worker started. Waiting for jobs...
```

The worker will then wait silently for jobs. You'll see activity after you submit leads.

**Leave this running throughout your session.**

---

#### TERMINAL 2: FastAPI Server

```bash
cd ~/autonomous-sdr
source venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected startup output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     ✓ Redis connection OK
INFO:     ✓ Ollama connection OK
INFO:     AutonomousSDR ready to accept leads
```

The `--reload` flag automatically restarts when you modify files.

**Leave this running throughout your session.**

---

#### TERMINAL 3: Testing/Interaction

Now you can test the system:

##### 3.1 Submit a Test Lead

```bash
cd ~/autonomous-sdr
source venv/bin/activate

# Create a variable to store the lead ID
LEAD_ID=$(curl -s -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sarah Chen",
    "email": "sarah.chen@stripe.com",
    "company": "Stripe"
  }' | jq -r '.id')

echo "Submitted lead with ID: $LEAD_ID"
```

Response:
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Sarah Chen",
  "email": "sarah.chen@stripe.com",
  "company": "Stripe",
  "status": "processing",
  "created_at": "2026-05-02T15:30:45"
}
```

---

##### 3.2 Watch Processing in Terminal 1

Check Terminal 1 (worker), you should see:

```
[Sarah Chen] Starting pipeline
[Sarah Chen] Enriched → FinTech, VP
[Sarah Chen] Analysis → verdict=Hot
[Sarah Chen] Validated → final=Hot confidence=0.95
[Sarah Chen] Pipeline complete ✓
```

This takes 3-15 seconds depending on Ollama response time.

---

##### 3.3 Retrieve Results

Back in Terminal 3:

```bash
curl http://localhost:8000/leads/$LEAD_ID | jq '.enrichment, .verdict'
```

Output:
```json
{
  "job_title": "VP of Engineering",
  "seniority": "VP",
  "company_size": "1000-5000",
  "industry": "FinTech",
  "revenue_estimate": "$1B+",
  "tech_stack": ["AWS", "Python", "PostgreSQL"],
  "confidence": 0.85,
  "enrichment_source": "domain_heuristics_v1"
}
{
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
```

✅ **System is working!**

---

### Phase 4: Advanced Testing

#### Generate 100 Test Leads (Terminal 3)

```bash
python scripts/generate_test_data.py
```

Output:
```
Submitting 100 test leads to http://localhost:8000/leads...
[1/100] ✓ Emily Harris @ Databricks
[2/100] ✓ Jessica Williams @ Twilio
...
[100/100] ✓ Michael Garcia @ GitHub

Done. 100/100 leads submitted successfully.
Wait for the worker to process them, then query GET /leads.
```

Watch Terminal 1 for processing logs. This will take 5-15 minutes depending on Ollama speed.

---

#### Query Results (Terminal 3)

```bash
# List first 10 leads
curl http://localhost:8000/leads?limit=10 | jq '.[] | {name, company, status}'

# Count processed leads
curl http://localhost:8000/leads?limit=1000 | jq '[.[] | select(.status == "complete")] | length'

# Count Hot/Warm/Cold verdicts
curl http://localhost:8000/leads?limit=1000 | jq '[.[] | select(.verdict != null) | .verdict.final_verdict] | group_by(.) | map({verdict: .[0], count: length})'
```

---

#### Run Tests (Terminal 3)

```bash
# Run all tests
pytest tests/ -v

# Run specific test file (no Ollama needed)
pytest tests/test_enrichment.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term
```

Expected output:
```
tests/test_enrichment.py::test_known_domain_returns_valid_output PASSED
tests/test_enrichment.py::test_unknown_domain_returns_valid_output PASSED
tests/test_enrichment.py::test_io_domain_infers_saas PASSED
tests/test_enrichment.py::test_enrichment_has_all_required_fields PASSED
tests/test_analysis_agent.py::test_parse_json_clean PASSED
tests/test_analysis_agent.py::test_parse_json_strips_markdown PASSED
tests/test_analysis_agent.py::test_analysis_output_validation PASSED
tests/test_validator_agent.py::test_parse_json_clean PASSED
tests/test_validator_agent.py::test_validated_output_confidence_clamped PASSED

======================== 9 passed in 2.45s ========================
```

---

### Phase 5: Using Makefile Shortcuts

Instead of remembering commands, use the Makefile:

```bash
make setup              # Install + init DB
make run-api            # Start API server
make run-worker         # Start worker
make test               # Run tests
make test-coverage      # Run with coverage report
make generate-data      # Create 100 test leads
make clean              # Remove cache files
make help               # Show all commands
```

---

### Phase 6: Interactive API Documentation

```bash
# Open Swagger UI
open http://localhost:8000/docs

# Or ReDoc
open http://localhost:8000/redoc
```

In the UI, you can:
- See all endpoints
- Read descriptions
- Try endpoints interactively
- See request/response schemas

---

## Database Inspection

Connect directly to PostgreSQL:

```bash
psql -U sdr_user -h localhost -p 5433 -d sdr_db

# Inside psql:
\dt                          # List tables
SELECT COUNT(*) FROM leads;  # Count leads
SELECT COUNT(*) FROM verdicts;
SELECT COUNT(*) FROM enrichments;

# Query specific lead with all data
SELECT l.id, l.name, l.email, l.company, l.status, 
       e.industry, e.seniority, v.final_verdict, v.confidence_score
FROM leads l
LEFT JOIN enrichments e ON l.id = e.lead_id
LEFT JOIN verdicts v ON l.id = v.lead_id
WHERE l.id = 'YOUR_LEAD_ID';

\q                           # Exit psql
```

---

## Troubleshooting

### Issue: "Cannot reach Ollama at http://localhost:11434"

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If it fails, start Ollama
ollama serve

# If mistral is not available
ollama pull mistral
```

### Issue: "Redis connection refused"

```bash
# Check if Redis is running
redis-cli ping

# If it fails, start Redis
brew services start redis

# Or start manually
redis-server
```

### Issue: "PostgreSQL connection error"

```bash
# Check if PostgreSQL is running
psql -U postgres -h localhost -p 5433 -c "SELECT 1"

# If it fails, start PostgreSQL
brew services start postgresql@18

# Verify database exists
psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT 1"
```

### Issue: "ModuleNotFoundError: No module named 'app'"

```bash
# Make sure you're in the correct directory
cd ~/autonomous-sdr

# Make sure venv is activated
source venv/bin/activate

# Verify imports work
python -c "import app; print('OK')"
```

### Issue: Worker shows no logs

- Check if leads are being submitted: `redis-cli LRANGE lead_jobs 0 -1`
- Check if Ollama is responding: `curl http://localhost:11434/api/tags`
- Check worker output for errors

---

## Summary Checklist

- [ ] Installed Redis, PostgreSQL, Ollama
- [ ] Created database and user
- [ ] Pulled Mistral model
- [ ] Created Python virtual environment
- [ ] Installed dependencies
- [ ] Initialized database tables
- [ ] Started worker (Terminal 1)
- [ ] Started API server (Terminal 2)
- [ ] Submitted test lead (Terminal 3)
- [ ] Watched it process in Terminal 1
- [ ] Retrieved results in Terminal 3
- [ ] Ran tests
- [ ] Opened http://localhost:8000/docs

**If all checkboxes are done, your system is fully functional! 🎉**

---

## Next Steps

1. **Integrate with your application**: Use the POST /leads endpoint
2. **Customize ICP settings**: Edit `.env` to match your business criteria
3. **Add more enrichment sources**: Extend EnrichmentProvider
4. **Deploy to production**: Use Docker (see README.md)
5. **Setup monitoring**: Log to your observability platform
6. **Connect to CRM**: Add webhook to your CRM/sales tool

---

## Files Reference

- **API**: `app/main.py`
- **Database**: `app/database/`
- **Agents**: `app/agents/`
- **Worker**: `app/worker/lead_worker.py`
- **Config**: `app/config.py` and `.env`
- **Tests**: `tests/`
- **Scripts**: `scripts/`

---

## Key Endpoints

```
GET  /health                 # Health check
POST /leads                  # Submit a lead
GET  /leads                  # List all leads (paginated)
GET  /leads/{lead_id}        # Get lead details

GET  /docs                   # Swagger UI
GET  /redoc                  # ReDoc
```

**You're all set! Happy lead qualifying! 🚀**
