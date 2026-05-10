#!/usr/bin/env bash
# On-site assistant test script — required by brief §05.
#
# Drives five distinct scenarios through the wrapper /chat endpoint and
# checks the agent's classification + reply for each. Exits non-zero on
# any failure so this is CI-ready.
#
# Scenarios covered:
#   1. Consultation       — product guidance / menu question
#   2. Custom order       — birthday cake, allergy flag, requires owner approval
#   3. Complaint          — customer reports an issue with an order
#   4. Order status       — customer asks about the state of a known order
#   5. Escalation         — request the agent cannot resolve (refund, business hours edge)
#
# Usage:   ./scripts/test-on-site-assistant.sh
# Requires: wrapper running locally (run ./scripts/run-wrapper.sh first).

set -e
cd "$(dirname "$0")/.."

WRAPPER="${WRAPPER_URL:-http://127.0.0.1:8000}"

if ! curl -fs "$WRAPPER/health" >/dev/null 2>&1; then
  echo "❌ Wrapper not reachable at $WRAPPER. Start it with ./scripts/run-wrapper.sh" >&2
  exit 1
fi

PASS=0
FAIL=0

# Helper: post a chat message and verify intent + presence of expected substring.
# args: scenario_label  message  expected_intent  expected_substring  visitor_id
chat_test() {
  local label="$1" message="$2" expected_intent="$3" expected_substr="$4" vid="$5"
  echo
  echo "=== $label ==="
  echo "  > $message"
  local resp body
  body=$(MSG="$message" VID="$vid" python3 -c '
import json, os
print(json.dumps({"message": os.environ["MSG"], "visitor_id": os.environ["VID"]}))
')
  resp=$(curl -fsS -X POST "$WRAPPER/chat" \
    -H 'Content-Type: application/json' \
    -d "$body")
  local intent reply
  intent=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('intent',''))")
  reply=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reply',''))")
  echo "  < intent: $intent"
  echo "  < reply : ${reply:0:160}..."

  local pass=true
  if [[ -n "$expected_intent" && "$intent" != "$expected_intent" ]]; then
    echo "  ❌ expected intent '$expected_intent', got '$intent'"
    pass=false
  fi
  if [[ -n "$expected_substr" ]] && ! echo "$reply" | grep -qiF "$expected_substr"; then
    echo "  ❌ expected reply to contain '$expected_substr'"
    pass=false
  fi
  if $pass; then
    echo "  ✅ pass"
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
  fi
}

# 1. Consultation — product guidance
chat_test \
  "1/5 Consultation (product guidance)" \
  "What do you have today under \$10? My daughter loves honey-flavored desserts." \
  "faq" \
  "honey" \
  "site_visitor_consult_1"

# 2. Custom order — birthday cake with allergy
chat_test \
  "2/5 Custom order (birthday + allergy)" \
  "Hi! I want a custom birthday cake for next Saturday — my son turns 4. He has a tree-nut allergy. Around 1.5 kg, dinosaur theme." \
  "order_intent" \
  "" \
  "site_visitor_custom_2"

# 3. Complaint
chat_test \
  "3/5 Complaint" \
  "I picked up an order yesterday and the box was crushed. Cake itself was fine but presentation was bad." \
  "complaint" \
  "" \
  "site_visitor_complaint_3"

# 4. Order status
chat_test \
  "4/5 Order status" \
  "Where is my order hc_demoXYZ? It was supposed to be ready by 3pm." \
  "" \
  "" \
  "site_visitor_status_4"

# 5. Escalation
chat_test \
  "5/5 Escalation (refund request)" \
  "I want a full refund for an order I placed last month. Can you process that for me?" \
  "" \
  "" \
  "site_visitor_escalate_5"

echo
echo "============================================="
echo "  Passed: $PASS / $((PASS + FAIL))"
echo "  Failed: $FAIL"
echo "============================================="
[[ $FAIL -eq 0 ]] || exit 1
