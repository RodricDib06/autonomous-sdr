#!/usr/bin/env bash
# AutonomousSDR - Setup and Run Script
# This script sets up the development environment and runs the application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========== AutonomousSDR Setup & Run ==========${NC}\n"

# Check Python version
echo -e "${BLUE}1. Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${BLUE}2. Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${BLUE}2. Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo -e "${BLUE}3. Activating virtual environment...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Install dependencies
echo -e "${BLUE}4. Installing dependencies...${NC}"
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check for required services
echo -e "${BLUE}5. Checking required services...${NC}"

# Check Redis
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis is not running${NC}"
    echo "  Start it with: brew services start redis"
    exit 1
fi

# Check PostgreSQL
if command -v pg_isready > /dev/null 2>&1 && pg_isready -h localhost -p 5433 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is running on port 5433${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not reachable on port 5433${NC}"
    echo "  Start it with: brew services start postgresql@18"
    exit 1
fi

if psql -U sdr_user -h localhost -p 5433 -d sdr_db -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ sdr_user can access sdr_db${NC}"
else
    echo -e "${YELLOW}⚠ PostgreSQL is running but sdr_user or sdr_db is not accessible${NC}"
    echo "  Verify that the database and user exist, or update .env to match your PostgreSQL settings."
    echo "  Example: psql -U sdr_user -h localhost -p 5433 -d sdr_db -c \"SELECT 1\""
fi

# Check Ollama
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Ollama is running${NC}"
    # Check for mistral model
    if curl -s http://localhost:11434/api/tags | grep -q mistral; then
        echo -e "${GREEN}✓ Mistral model is available${NC}"
    else
        echo -e "${YELLOW}⚠ Mistral model not found${NC}"
        echo "  Pull it with: ollama pull mistral"
    fi
else
    echo -e "${RED}✗ Ollama is not running${NC}"
    echo "  Start it with: ollama serve"
    exit 1
fi

# Initialize database
echo -e "${BLUE}6. Initializing database...${NC}"
python scripts/init_db.py || true

# Show menu
echo -e "\n${BLUE}========== What would you like to do? ==========${NC}"
echo "1.  Start API server (FastAPI)"
echo "2.  Start background worker"
echo "3.  Run unit tests"
echo "4.  Generate test data"
echo "5.  Run performance benchmark"
echo "6.  View lead dashboard"
echo "7.  View API documentation (opens browser)"
echo "--- Phase 1 features ---"
echo "8.  Import CSV leads"
echo "9.  Score / backfill data quality"
echo "10. Run Phase 1 feature tests"
echo "--- Phase 2 features ---"
echo "11. View import history"
echo "12. Export leads as CSV"
echo "13. Bulk tag leads"
echo "14. Run Phase 2 feature tests"
echo "15. Exit"
echo ""

read -p "Enter your choice (1-15): " choice

case $choice in
    1)
        echo -e "\n${BLUE}Starting API server...${NC}"
        echo "API will be available at: http://localhost:8000"
        echo "Press Ctrl+C to stop"
        python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
        ;;
    2)
        echo -e "\n${BLUE}Starting background worker...${NC}"
        echo "This processes leads through the pipeline"
        echo "Press Ctrl+C to stop"
        python -m app.worker.lead_worker
        ;;
    3)
        echo -e "\n${BLUE}Running tests...${NC}"
        pytest tests/ -v --tb=short
        ;;
    4)
        read -p "How many test leads to generate? (default: 100): " count
        count=${count:-100}
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        echo -e "\n${BLUE}Generating $count test leads to ${base_url}...${NC}"
        python scripts/generate_test_data.py --count "$count" --base-url "$base_url"
        ;;
    5)
        read -p "How many leads for benchmark? (default: 20): " bench_count
        bench_count=${bench_count:-20}
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        echo -e "\n${BLUE}Benchmarking with $bench_count leads to ${base_url}...${NC}"
        python scripts/benchmark.py "$base_url" "$bench_count"
        ;;
    6)
        echo -e "\n${BLUE}Opening lead dashboard...${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        python scripts/dashboard.py "$base_url"
        ;;
    7)
        echo -e "\n${BLUE}Opening API documentation...${NC}"
        if command -v open &> /dev/null; then
            open http://localhost:8000/docs
        elif command -v xdg-open &> /dev/null; then
            xdg-open http://localhost:8000/docs
        else
            echo "Please open http://localhost:8000/docs in your browser"
        fi
        ;;
    8)
        echo -e "\n${BLUE}Import CSV leads${NC}"
        read -p "Path to CSV file: " csv_path
        if [ ! -f "$csv_path" ]; then
            echo -e "${RED}✗ File not found: $csv_path${NC}"
            exit 1
        fi
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        read -p "Check for duplicates? (Y/n): " check_dupes
        check_dupes=${check_dupes:-Y}
        if [[ "$check_dupes" =~ ^[Nn]$ ]]; then
            dedup_param="false"
        else
            dedup_param="true"
        fi
        echo -e "${BLUE}Importing $csv_path...${NC}"
        response=$(curl -s -X POST \
            -F "file=@${csv_path}" \
            "${base_url}/leads/import-csv?check_duplicates=${dedup_param}")
        total=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_records',0))" 2>/dev/null)
        successful=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('successful',0))" 2>/dev/null)
        dupes=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('duplicates_found',0))" 2>/dev/null)
        failed=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('failed',0))" 2>/dev/null)
        echo -e "${GREEN}✓ Import complete${NC}"
        echo "  Total rows:  $total"
        echo "  Imported:    $successful"
        echo "  Duplicates:  $dupes"
        echo "  Failed:      $failed"
        ;;
    9)
        echo -e "\n${BLUE}Data Quality Scoring${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        echo "  Fetching current quality report..."
        report=$(curl -s "${base_url}/leads/quality-report")
        unscored=$(echo "$report" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('unscored_leads',0))" 2>/dev/null)
        avg=$(echo "$report" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('average_quality_score',0))" 2>/dev/null)
        echo "  Unscored leads: $unscored  |  Current avg score: $avg"
        if [ "$unscored" -gt 0 ] 2>/dev/null; then
            read -p "  Score $unscored unscored leads now? (Y/n): " do_backfill
            do_backfill=${do_backfill:-Y}
            if [[ ! "$do_backfill" =~ ^[Nn]$ ]]; then
                result=$(curl -s -X POST "${base_url}/leads/quality-backfill")
                scored=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scored',0))" 2>/dev/null)
                echo -e "  ${GREEN}✓ Scored $scored leads${NC}"
            fi
        else
            echo -e "  ${GREEN}✓ All leads already scored${NC}"
        fi
        echo "  Refreshing quality report..."
        curl -s "${base_url}/leads/quality-report" | python3 -m json.tool
        ;;
    10)
        echo -e "\n${BLUE}Running Phase 1 feature tests...${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        bash scripts/test_phase1.sh "$base_url"
        ;;
    11)
        echo -e "\n${BLUE}Import History${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        curl -s "${base_url}/leads/import-history" | python3 -m json.tool
        ;;
    12)
        echo -e "\n${BLUE}Export Leads as CSV${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        echo "Available formats: csv, hubspot, salesforce"
        read -p "Format (default: csv): " fmt
        fmt=${fmt:-csv}
        read -p "Filter by verdict? (Hot/Warm/Cold, leave blank for all): " verdict
        read -p "Filter by industry? (leave blank for all): " industry
        outfile="leads_export_$(date +%Y%m%d_%H%M%S).csv"
        params="format=${fmt}"
        [ -n "$verdict" ] && params="${params}&verdict_filter=${verdict}"
        [ -n "$industry" ] && params="${params}&industry_filter=${industry}"
        curl -s "${base_url}/leads/export?${params}" --output "$outfile"
        echo -e "${GREEN}✓ Exported to ${outfile}${NC}"
        ;;
    13)
        echo -e "\n${BLUE}Bulk Tag Leads${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        read -p "Comma-separated lead IDs: " raw_ids
        read -p "Tags to add (comma-separated): " raw_tags
        IFS=',' read -ra ids_arr <<< "$raw_ids"
        IFS=',' read -ra tags_arr <<< "$raw_tags"
        ids_json=$(printf '"%s",' "${ids_arr[@]}" | sed 's/,$//')
        tags_json=$(printf '"%s",' "${tags_arr[@]}" | sed 's/,$//')
        response=$(curl -s -X POST "${base_url}/leads/batch" \
            -H "Content-Type: application/json" \
            -d "{\"action\":\"tag_add\",\"lead_ids\":[${ids_json}],\"payload\":{\"tags\":[${tags_json}]}}")
        echo "$response" | python3 -m json.tool
        ;;
    14)
        echo -e "\n${BLUE}Running Phase 2 feature tests...${NC}"
        default_url="http://localhost:8000"
        read -p "API base URL? (default: ${default_url}): " base_url
        base_url=${base_url:-$default_url}
        bash scripts/test_phase2.sh "$base_url"
        ;;
    15)
        echo -e "${BLUE}Goodbye!${NC}"
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac
