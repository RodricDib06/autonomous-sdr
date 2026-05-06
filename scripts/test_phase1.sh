#!/usr/bin/env bash
# Test Phase 1 Features
# Run this after the API server is running

# Check server is up before running tests
if ! curl -s --max-time 3 "${1:-http://localhost:8000}/health" > /dev/null 2>&1; then
    echo "❌ Server not reachable at ${1:-http://localhost:8000}"
    echo "   Start it with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    exit 1
fi

BASE_URL="${1:-http://localhost:8000}"

echo "🧪 Testing Phase 1 Features..."
echo "API Base URL: $BASE_URL"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# 1. Test Email Validation
echo -e "${BLUE}1. Testing Email Validation${NC}"
echo "   Validating corporate email..."
response=$(curl -s -X POST "$BASE_URL/validate/email?email=john@company.com")
if echo "$response" | grep -q '"is_valid":true'; then
    echo -e "   ${GREEN}✓ Corporate email validation passed${NC}"
else
    echo -e "   ${RED}✗ Corporate email validation failed${NC}"
    echo "   Response: $response"
fi

echo "   Validating temporary email..."
response=$(curl -s -X POST "$BASE_URL/validate/email?email=test@tempmail.com")
if echo "$response" | grep -q '"is_temporary":true'; then
    echo -e "   ${GREEN}✓ Temporary email detection passed${NC}"
else
    echo -e "   ${RED}✗ Temporary email detection failed${NC}"
fi

echo ""

# 2. Test Slack Configuration
echo -e "${BLUE}2. Testing Slack Configuration${NC}"
echo "   Checking Slack config status..."
response=$(curl -s "$BASE_URL/config/slack")
echo -e "   ${GREEN}✓ Slack config endpoint working${NC}"
echo "   Response: $response"

echo ""

# 3. Test CSV Import
echo -e "${BLUE}3. Testing CSV Import${NC}"
echo "   Creating test CSV file..."
TS=$(date +%s)
cat > /tmp/test_leads.csv << EOF
name,email,company,source
Test User 1,testuser1+${TS}@example.com,Test Company 1,test
Test User 2,testuser2+${TS}@example.com,Test Company 2,test
EOF

echo "   Importing CSV file..."
response=$(curl -s -X POST -F "file=@/tmp/test_leads.csv" \
  "$BASE_URL/leads/import-csv?check_duplicates=true")

if echo "$response" | grep -q '"successful"'; then
    successful=$(echo "$response" | grep -o '"successful":[0-9]*' | grep -o '[0-9]*')
    total=$(echo "$response" | grep -o '"total_records":[0-9]*' | grep -o '[0-9]*')
    echo -e "   ${GREEN}✓ CSV import passed (${successful}/${total} successful)${NC}"
else
    echo -e "   ${RED}✗ CSV import failed${NC}"
    echo "   Response: $response"
fi

rm /tmp/test_leads.csv

echo ""

# 4. Test Deduplication Report
echo -e "${BLUE}4. Testing Deduplication Report${NC}"
echo "   Fetching duplicate report..."
response=$(curl -s "$BASE_URL/leads/duplicates/report")
if echo "$response" | grep -q '"total_leads"'; then
    total=$(echo "$response" | grep -o '"total_leads":[0-9]*' | grep -o '[0-9]*')
    echo -e "   ${GREEN}✓ Duplicate report generated (${total} total leads)${NC}"
else
    echo -e "   ${RED}✗ Duplicate report failed${NC}"
fi

echo ""

# 5. Test Stats Endpoint
echo -e "${BLUE}5. Testing Statistics${NC}"
echo "   Fetching pipeline statistics..."
response=$(curl -s "$BASE_URL/leads/stats")
if echo "$response" | grep -q '"total_leads"'; then
    total=$(echo "$response" | grep -o '"total_leads":[0-9]*' | grep -o '[0-9]*')
    echo -e "   ${GREEN}✓ Statistics endpoint working (${total} total leads)${NC}"
else
    echo -e "   ${RED}✗ Statistics endpoint failed${NC}"
fi

echo ""

# 6. Test Data Quality Report
echo -e "${BLUE}6. Testing Data Quality Report${NC}"
echo "   Fetching quality report..."
response=$(curl -s "$BASE_URL/leads/quality-report")
if echo "$response" | grep -q '"total_leads"'; then
    total=$(echo "$response" | grep -o '"total_leads":[0-9]*' | grep -o '[0-9]*')
    avg=$(echo "$response" | grep -o '"average_quality_score":[0-9.]*' | grep -o '[0-9.]*')
    echo -e "   ${GREEN}✓ Quality report generated (${total} leads, avg score: ${avg})${NC}"
else
    echo -e "   ${RED}✗ Quality report failed${NC}"
    echo "   Response: $response"
fi

echo ""

# 7. Test Per-Lead Quality Score (use first lead from list)
echo -e "${BLUE}7. Testing Per-Lead Quality Score${NC}"
first_lead_id=$(curl -s "$BASE_URL/leads?limit=1" | grep -o '"id":"[^"]*"' | head -1 | grep -o '"[^"]*"$' | tr -d '"')
if [ -n "$first_lead_id" ]; then
    response=$(curl -s "$BASE_URL/leads/${first_lead_id}/quality-score")
    if echo "$response" | grep -q '"data_quality_score"'; then
        score=$(echo "$response" | grep -o '"data_quality_score":[0-9.]*' | grep -o '[0-9.]*')
        echo -e "   ${GREEN}✓ Per-lead quality score working (score: ${score})${NC}"
    else
        echo -e "   ${RED}✗ Per-lead quality score failed${NC}"
        echo "   Response: $response"
    fi
else
    echo -e "   ${BLUE}⚠ No leads in database to test per-lead quality score${NC}"
fi

echo ""
echo -e "${GREEN}✅ Phase 1 Feature Tests Complete!${NC}"
echo ""
echo "📚 Documentation: See PHASE1_FEATURES.md for detailed feature descriptions"
echo "📝 Sample CSV: See sample_leads.csv for import testing"
