#!/usr/bin/env bash
# Seed sandbox-side state across every channel the evaluator scores against.
#
# What this drives, in one go:
#   - Instagram: inject + reply, list threads, schedule + approve + publish a post
#   - WhatsApp:  inject + reply, list threads
#   - Google Business: reply to existing reviews, simulate a community post
#   - Marketing: create + launch + generate_leads + route_lead + adjust + report,
#                across all 5 campaigns of the $500/month plan
#   - World:     run the launch-day-revenue-engine scenario end-to-end
#
# Why you need this on a fresh clone:
# `evaluator_generate_team_report` reads sandbox-side state, not our local
# evidence/log.jsonl. If the team's sandbox state is empty, the marketing /
# IG / WA / GB rubric lines score low even when the code works.
#
# Safe to re-run. The sandbox idempotently appends; campaign IDs, post IDs,
# and review reply IDs are unique per call.

set -e
cd "$(dirname "$0")/.."

if ! grep -qE '^SBC_TEAM_TOKEN=' .env 2>/dev/null; then
  echo "ERROR: .env is missing SBC_TEAM_TOKEN. Copy .env.example to .env first." >&2
  exit 1
fi

echo "Seeding sandbox state — this hits the live sandbox MCP and takes ~60s."
echo
uv run --active --project wrapper python scripts/seed-evaluator-evidence.py
echo
echo "Done. Re-running evaluator_generate_team_report to refresh the score:"
TOKEN=$(grep -E '^SBC_TEAM_TOKEN=' .env | cut -d= -f2)
URL=$(grep -E '^SBC_MCP_URL=' .env | cut -d= -f2)
curl -fsS -m 30 -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Team-Token: $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"evaluator_generate_team_report","arguments":{}}}' \
  | python3 -m json.tool | head -40
