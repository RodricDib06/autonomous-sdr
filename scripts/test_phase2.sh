#!/usr/bin/env bash
# Test Phase 2 Features
# Run this after the API server is running

BASE_URL="${1:-http://localhost:8000}"

echo "🧪 Testing Phase 2 Features..."
echo "API Base URL: $BASE_URL"
echo ""

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Check server is up
if ! curl -s --max-time 3 "${BASE_URL}/health" > /dev/null 2>&1; then
    echo "❌ Server not reachable at ${BASE_URL}"
    echo "   Start it with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    exit 1
fi

# 1. Test CSV import creates history record
echo -e "${BLUE}1. Testing Import History${NC}"
TS=$(date +%s)
cat > /tmp/test_phase2.csv << EOF
name,email,company,source
Phase2 User,phase2+${TS}@example.com,Phase2 Co,test
EOF

curl -s -X POST -F "file=@/tmp/test_phase2.csv" \
    "${BASE_URL}/leads/import-csv?check_duplicates=true" > /dev/null

response=$(curl -s "${BASE_URL}/leads/import-history")
if echo "$response" | grep -q '"count"'; then
    count=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
    echo -e "   ${GREEN}✓ Import history endpoint working ($count records)${NC}"
else
    echo -e "   ${RED}✗ Import history failed${NC}"
    echo "   Response: $response"
fi
rm /tmp/test_phase2.csv
echo ""

# 2. Test JSON export
echo -e "${BLUE}2. Testing JSON Export${NC}"
response=$(curl -s "${BASE_URL}/leads/export?format=json")
if echo "$response" | grep -q '"export"'; then
    count=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
    echo -e "   ${GREEN}✓ JSON export working ($count leads)${NC}"
else
    echo -e "   ${RED}✗ JSON export failed${NC}"
fi
echo ""

# 3. Test CSV export
echo -e "${BLUE}3. Testing CSV Export${NC}"
response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/leads/export?format=csv")
http_code=$(echo "$response" | tail -1)
if [ "$http_code" = "200" ]; then
    echo -e "   ${GREEN}✓ CSV export returning 200${NC}"
else
    echo -e "   ${RED}✗ CSV export failed (HTTP $http_code)${NC}"
fi
echo ""

# 4. Test HubSpot export
echo -e "${BLUE}4. Testing HubSpot Export${NC}"
response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/leads/export?format=hubspot")
http_code=$(echo "$response" | tail -1)
if [ "$http_code" = "200" ]; then
    echo -e "   ${GREEN}✓ HubSpot CSV export returning 200${NC}"
else
    echo -e "   ${RED}✗ HubSpot export failed (HTTP $http_code)${NC}"
fi
echo ""

# 5. Test Salesforce export
echo -e "${BLUE}5. Testing Salesforce Export${NC}"
response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/leads/export?format=salesforce")
http_code=$(echo "$response" | tail -1)
if [ "$http_code" = "200" ]; then
    echo -e "   ${GREEN}✓ Salesforce CSV export returning 200${NC}"
else
    echo -e "   ${RED}✗ Salesforce export failed (HTTP $http_code)${NC}"
fi
echo ""

# 6. Test batch tag_add
echo -e "${BLUE}6. Testing Batch Tag Add${NC}"
first_lead_id=$(curl -s "${BASE_URL}/leads?limit=1" | python3 -c \
    "import sys,json; leads=json.load(sys.stdin); print(leads[0]['id'] if leads else '')" 2>/dev/null)

if [ -n "$first_lead_id" ]; then
    response=$(curl -s -X POST "${BASE_URL}/leads/batch" \
        -H "Content-Type: application/json" \
        -d "{\"action\":\"tag_add\",\"lead_ids\":[\"${first_lead_id}\"],\"payload\":{\"tags\":[\"phase2-test\"]}}")
    if echo "$response" | grep -q '"succeeded"'; then
        succeeded=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('succeeded',0))" 2>/dev/null)
        echo -e "   ${GREEN}✓ Batch tag_add working ($succeeded leads tagged)${NC}"
    else
        echo -e "   ${RED}✗ Batch tag_add failed${NC}"
        echo "   Response: $response"
    fi
else
    echo -e "   ${BLUE}⚠ No leads in database to test batch actions${NC}"
fi
echo ""

# 7. Test batch archive
echo -e "${BLUE}7. Testing Batch Archive${NC}"
if [ -n "$first_lead_id" ]; then
    response=$(curl -s -X POST "${BASE_URL}/leads/batch" \
        -H "Content-Type: application/json" \
        -d "{\"action\":\"archive\",\"lead_ids\":[\"${first_lead_id}\"],\"payload\":{}}")
    if echo "$response" | grep -q '"succeeded"'; then
        echo -e "   ${GREEN}✓ Batch archive working${NC}"
    else
        echo -e "   ${RED}✗ Batch archive failed${NC}"
    fi
else
    echo -e "   ${BLUE}⚠ No leads to test archive${NC}"
fi
echo ""

echo -e "${GREEN}✅ Phase 2 Feature Tests Complete!${NC}"
