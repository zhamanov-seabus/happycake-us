#!/usr/bin/env bash
# End-to-end demo for the evaluator. Simulates: customer DMs HappyCake on
# Instagram → agent decides → owner Telegram receives card → owner approves
# → POS order created in sandbox, kitchen ticket queued, customer reply sent.
#
# Prerequisites (the README walks through them):
#   1. cp .env.example .env  (and fill in the four secrets)
#   2. uvicorn is running (./scripts/run-wrapper.sh)
#   3. The owner has /start'd @happy_cake_owner_bot in Telegram
#
# This script does NOT need ngrok — it bypasses the registered webhook by
# POSTing the payload directly to /webhook/instagram, which is what the sandbox
# forwarder would do anyway.

set -e
cd "$(dirname "$0")/.."

WRAPPER="${WRAPPER_URL:-http://127.0.0.1:8000}"

echo "Step 1 — wrapper health"
curl -fsS "$WRAPPER/health" | python3 -m json.tool

echo
echo "Step 2 — clear today's evidence log (start fresh for the demo)"
mkdir -p evidence
: > evidence/log.jsonl
echo "  evidence/log.jsonl truncated"

echo
echo "Step 3 — simulate inbound Instagram DM via sandbox (order-intent: whole honey cake)"
echo "  Using a sandbox-seeded sender if the simulator has any prior threads."
TOKEN=$(grep -E '^SBC_TEAM_TOKEN=' .env | cut -d= -f2)
URL=$(grep -E '^SBC_MCP_URL=' .env | cut -d= -f2)

# Try to pick a sandbox-seeded IG handle from prior threads. Falls back
# to a fresh handle if the simulator has none.
SENDER=$(curl -fsS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Team-Token: $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"instagram_list_dm_threads","arguments":{}}}' \
  | python3 -c "
import sys, json
try:
  r = json.load(sys.stdin)
  d = json.loads(r['result']['content'][0]['text'])
  ins = d.get('inbound', [])
  if ins:
    print(ins[-1].get('from') or ins[-1].get('threadId') or 'maria_lopez_demo')
  else:
    print('maria_lopez_demo')
except Exception:
  print('maria_lopez_demo')
")
echo "  Using IG sender: $SENDER"

curl -fsS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Team-Token: $TOKEN" \
  -d "$(python3 -c "
import json,sys
print(json.dumps({
  'jsonrpc':'2.0','id':1,
  'method':'tools/call',
  'params':{'name':'instagram_inject_dm','arguments':{
    'threadId': sys.argv[1],
    'from': sys.argv[1],
    'message': \"Hi! I'd love to pick up a whole honey cake this Saturday around 3pm. Is that doable?\"
  }}
}))
" "$SENDER")" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['result']['content'][0]['text'])"

echo
echo "Step 4 — give Claude a moment, then show evidence log"
sleep 2
echo "---- evidence/log.jsonl ----"
cat evidence/log.jsonl
echo
echo "----------------------------"

echo
echo "Step 5 — over to you in Telegram. Open @happy_cake_owner_bot, you should see"
echo "         a card titled 'New instagram order — Maria Lopez'. Tap ✅ Approve."
echo "         Then re-run the script with --post-approval to confirm the order chain."

if [[ "${1:-}" == "--post-approval" ]]; then
  echo
  echo "Step 6 — checking sandbox for created order"
  TOKEN=$(grep -E '^SBC_TEAM_TOKEN=' .env | cut -d= -f2)
  URL=$(grep -E '^SBC_MCP_URL=' .env | cut -d= -f2)
  curl -fsS -X POST "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "X-Team-Token: $TOKEN" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"square_recent_orders","arguments":{"limit":3}}}' \
    | python3 -m json.tool
fi
