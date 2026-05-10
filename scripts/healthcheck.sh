#!/usr/bin/env bash
# HappyCake healthcheck — run this FIRST on a fresh clone.
# Tells you exactly which piece of the stack is missing or stale before you
# spend 10 minutes wondering why the demo isn't working.
#
# Exit codes:
#   0 — all green
#   1 — fatal: env / repo state issue (will not work)
#   2 — warning: one or more services not responding (probably fixable)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$1"; }

fatal=0
warn_count=0

echo
echo "HappyCake healthcheck — $(date)"
echo

# --- 1. Repo + env -------------------------------------------------------
echo "1. Repo + .env"
if [[ ! -f .env ]]; then
  fail ".env missing — run: cp .env.example .env && \$EDITOR .env"
  fatal=1
else
  ok ".env present"
fi

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
  for var in SBC_TEAM_TOKEN SBC_MCP_URL TELEGRAM_BOT_TOKEN TELEGRAM_OWNER_CHAT_ID; do
    val="${!var:-}"
    if [[ -z "$val" || "$val" == REPLACE_* ]]; then
      fail "$var not set in .env"
      fatal=1
    else
      ok "$var set"
    fi
  done
  if [[ -z "${PUBLIC_TUNNEL_URL:-}" || "${PUBLIC_TUNNEL_URL:-}" == https://your-tunnel* ]]; then
    warn "PUBLIC_TUNNEL_URL not set — webhooks from the sandbox will not reach this machine"
    warn_count=$((warn_count+1))
  else
    ok "PUBLIC_TUNNEL_URL=$PUBLIC_TUNNEL_URL"
  fi
fi
echo

# --- 2. Tooling ----------------------------------------------------------
echo "2. CLI tools"
for cmd in claude uv node npm python3 jq curl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd on PATH"
  else
    fail "$cmd missing"
    fatal=1
  fi
done
echo

# --- 3. Wrapper ---------------------------------------------------------
echo "3. Wrapper service (FastAPI on :${WRAPPER_PORT:-8000})"
PORT="${WRAPPER_PORT:-8000}"
if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  health="$(curl -s --max-time 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null)"
  ok "wrapper healthy on :${PORT}"
  ok "  ${health}"
else
  warn "wrapper not running on :${PORT} — start it with: ./scripts/run-wrapper.sh"
  warn_count=$((warn_count+1))
fi
echo

# --- 4. Sandbox MCP ------------------------------------------------------
echo "4. Sandbox MCP reachability"
if [[ -n "${SBC_TEAM_TOKEN:-}" && -n "${SBC_MCP_URL:-}" && "$SBC_TEAM_TOKEN" != REPLACE_* ]]; then
  payload='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"square_list_catalog","arguments":{"limit":1}}}'
  resp="$(curl -s --max-time 8 -X POST "$SBC_MCP_URL" \
    -H "X-Team-Token: $SBC_TEAM_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$payload" 2>&1)"
  if printf '%s' "$resp" | grep -q '"result"'; then
    ok "sandbox MCP responding (square_list_catalog returned result)"
  else
    fail "sandbox MCP not responding correctly: $(printf '%s' "$resp" | head -c 200)"
    warn_count=$((warn_count+1))
  fi
else
  warn "SBC_TEAM_TOKEN or SBC_MCP_URL missing — skipping MCP probe"
fi
echo

# --- 5. Telegram bot ------------------------------------------------------
echo "5. Telegram owner bot"
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && "$TELEGRAM_BOT_TOKEN" != REPLACE_* ]]; then
  bot_resp="$(curl -s --max-time 5 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null)"
  if printf '%s' "$bot_resp" | grep -q '"ok":true'; then
    bot_name="$(printf '%s' "$bot_resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["username"])' 2>/dev/null || echo "?")"
    ok "Telegram bot reachable as @${bot_name}"
    if [[ -z "${TELEGRAM_OWNER_CHAT_ID:-}" || "$TELEGRAM_OWNER_CHAT_ID" == REPLACE_* ]]; then
      warn "TELEGRAM_OWNER_CHAT_ID not set — handoffs will be skipped"
      warn_count=$((warn_count+1))
    else
      ok "TELEGRAM_OWNER_CHAT_ID=${TELEGRAM_OWNER_CHAT_ID}"
      ok "  Reminder: DM /start to your bot once before the first run."
    fi
  else
    fail "Telegram bot token rejected by API: $(printf '%s' "$bot_resp" | head -c 160)"
    fatal=1
  fi
fi
echo

# --- 6. Tunnel staleness check (the silent killer) -----------------------
echo "6. Public tunnel"
if [[ -n "${PUBLIC_TUNNEL_URL:-}" && "${PUBLIC_TUNNEL_URL:-}" != https://your-tunnel* ]]; then
  tunnel_resp="$(curl -sf --max-time 5 "${PUBLIC_TUNNEL_URL}/health" 2>/dev/null)"
  if [[ -n "$tunnel_resp" ]]; then
    ok "tunnel ${PUBLIC_TUNNEL_URL} reaches local wrapper"
  else
    fail "tunnel ${PUBLIC_TUNNEL_URL} did NOT reach the wrapper"
    fail "  Cloudflare quick tunnels rotate URLs on every restart."
    fail "  Check: cloudflared tunnel --url http://localhost:${PORT}"
    fail "  Then update PUBLIC_TUNNEL_URL in .env and run: ./scripts/register-webhooks.sh"
    warn_count=$((warn_count+1))
  fi
else
  warn "PUBLIC_TUNNEL_URL not set — local-only mode (demo.sh works; live IG/WA forwarding does not)"
fi
echo

# --- Summary --------------------------------------------------------------
if [[ $fatal -ne 0 ]]; then
  printf "\033[31mFATAL\033[0m — fix the ✗ lines above before running ./scripts/demo.sh.\n"
  exit 1
elif [[ $warn_count -gt 0 ]]; then
  printf "\033[33mREADY WITH WARNINGS\033[0m — %d soft issue(s). Demo will work for local-only flows.\n" "$warn_count"
  exit 2
else
  printf "\033[32mALL GREEN\033[0m — go run ./scripts/seed.sh && ./scripts/demo.sh\n"
  exit 0
fi
