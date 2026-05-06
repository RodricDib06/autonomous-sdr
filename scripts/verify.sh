#!/usr/bin/env bash
# AutonomousSDR - Verification Script
# Checks that all components are properly installed and configured

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

check() {
    echo -e "${BLUE}→${NC} $1"
}

pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

echo -e "${BLUE}========== AutonomousSDR Verification ==========${NC}\n"

# Check Python
check "Python 3.11+"
python3 --version > /dev/null 2>&1 && pass "Python 3.11+ installed" || fail "Python 3.11+ not found"

# Check virtual environment
check "Virtual environment"
[ -d "venv" ] && pass "venv directory exists" || fail "venv directory not found"

# Check dependencies
check "Dependencies"
if source venv/bin/activate 2>/dev/null && python -c "import fastapi, redis, sqlalchemy, pydantic" 2>/dev/null; then
    pass "All dependencies installed"
else
    fail "Missing dependencies"
fi

# Check environment file
check ".env configuration"
[ -f ".env" ] && pass ".env file exists" || fail ".env file not found"

# Check database.py
check "Database connection file"
[ -f "app/database/connection.py" ] && pass "connection.py exists" || fail "connection.py not found"

# Check models
check "Database models"
[ -f "app/database/models.py" ] && pass "models.py exists" || fail "models.py not found"

# Check agents
check "Agent implementations"
[ -f "app/agents/enrichment_agent.py" ] && pass "enrichment_agent.py exists" || fail "enrichment_agent.py not found"
[ -f "app/agents/analysis_agent.py" ] && pass "analysis_agent.py exists" || fail "analysis_agent.py not found"
[ -f "app/agents/validator_agent.py" ] && pass "validator_agent.py exists" || fail "validator_agent.py not found"

# Check worker
check "Background worker"
[ -f "app/worker/lead_worker.py" ] && pass "lead_worker.py exists" || fail "lead_worker.py not found"

# Check tests
check "Test files"
[ -f "tests/__init__.py" ] && pass "tests/__init__.py exists" || fail "tests/__init__.py not found"
[ -f "tests/conftest.py" ] && pass "tests/conftest.py exists" || fail "tests/conftest.py not found"
[ -f "tests/test_enrichment.py" ] && pass "test_enrichment.py exists" || fail "test_enrichment.py not found"

# Check scripts
check "Setup scripts"
[ -f "scripts/init_db.py" ] && pass "init_db.py exists" || fail "init_db.py not found"
[ -f "scripts/setup_and_run.sh" ] && pass "setup_and_run.sh exists" || fail "setup_and_run.sh not found"
[ -f "scripts/generate_test_data.py" ] && pass "generate_test_data.py exists" || fail "generate_test_data.py not found"

# Check documentation
check "Documentation"
[ -f "README.md" ] && pass "README.md exists" || fail "README.md not found"
[ -f "QUICKSTART.md" ] && pass "QUICKSTART.md exists" || fail "QUICKSTART.md not found"
[ -f "RUNNING.md" ] && pass "RUNNING.md exists" || fail "RUNNING.md not found"
[ -f "AUDIT_REPORT.md" ] && pass "AUDIT_REPORT.md exists" || fail "AUDIT_REPORT.md not found"

# Check configuration files
check "Configuration files"
[ -f "pytest.ini" ] && pass "pytest.ini exists" || fail "pytest.ini not found"
[ -f ".env.example" ] && pass ".env.example exists" || fail ".env.example not found"
[ -f "Makefile" ] && pass "Makefile exists" || fail "Makefile not found"

# Check Python syntax
check "Python syntax"
if source venv/bin/activate 2>/dev/null && python -m py_compile app/main.py 2>/dev/null; then
    pass "app/main.py - Valid syntax"
else
    fail "app/main.py - Syntax error"
fi

if source venv/bin/activate 2>/dev/null && python -m py_compile app/worker/lead_worker.py 2>/dev/null; then
    pass "lead_worker.py - Valid syntax"
else
    fail "lead_worker.py - Syntax error"
fi

# Check imports
check "Python imports"
if source venv/bin/activate 2>/dev/null && python -c "from app.config import settings; from app.database.models import Lead; print('OK')" 2>/dev/null; then
    pass "Core imports working"
else
    fail "Core imports failing"
fi

# Check services
echo ""
check "External services (must be running)"

# Redis
if redis-cli ping > /dev/null 2>&1; then
    pass "Redis is running"
else
    fail "Redis not running (required)"
fi

# PostgreSQL
if psql -U postgres -h localhost -p 5433 -c "SELECT 1" > /dev/null 2>&1; then
    pass "PostgreSQL is running"
else
    fail "PostgreSQL not running (required)"
fi

# Ollama
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    pass "Ollama is running"
    if curl -s http://localhost:11434/api/tags | grep -q mistral; then
        pass "Mistral model is available"
    else
        warn "Mistral model not found (optional, will download on first use)"
    fi
else
    fail "Ollama not running (required)"
fi

# Database
echo ""
check "Database setup"
if psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT COUNT(*) FROM leads" > /dev/null 2>&1; then
    pass "Database sdr_db is accessible"
    count=$(psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT COUNT(*) FROM leads" 2>/dev/null | tail -1)
    pass "Database has $count leads"
else
    warn "Database sdr_db not initialized (run: python scripts/init_db.py)"
fi

# Summary
echo ""
echo -e "${BLUE}========== Summary ==========${NC}"
echo -e "${GREEN}Passed: $PASSED${NC}"
[ $WARNINGS -gt 0 ] && echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
[ $FAILED -gt 0 ] && echo -e "${RED}Failed: $FAILED${NC}"

if [ $FAILED -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All checks passed! System is ready to run.${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Read RUNNING.md for detailed instructions"
    echo "2. Or use: bash scripts/setup_and_run.sh"
    echo ""
    exit 0
else
    echo ""
    echo -e "${RED}✗ Some checks failed. Please fix the issues above.${NC}"
    echo ""
    echo "Common fixes:"
    echo "- Redis: brew services start redis"
    echo "- PostgreSQL: brew services start postgresql@18"
    echo "- Ollama: ollama serve"
    echo "- Database: python scripts/init_db.py"
    echo ""
    exit 1
fi
