#!/usr/bin/env bash
# Registers the wrapper's webhook URLs with the sandbox MCP. Call once after
# starting your ngrok / cloudflared tunnel and updating PUBLIC_TUNNEL_URL in .env.
set -e
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env — copy .env.example and fill in PUBLIC_TUNNEL_URL." >&2
  exit 1
fi

TOKEN=$(grep -E '^SBC_TEAM_TOKEN=' .env | cut -d= -f2)
URL=$(grep -E '^SBC_MCP_URL=' .env | cut -d= -f2)
TUNNEL=$(grep -E '^PUBLIC_TUNNEL_URL=' .env | cut -d= -f2)

if [[ -z "$TUNNEL" ]]; then
  echo "PUBLIC_TUNNEL_URL is empty in .env — start ngrok and paste the URL." >&2
  exit 1
fi

call() {
  curl -fsS -X POST "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "X-Team-Token: $TOKEN" \
    -d "$1"
}

echo "Registering Instagram webhook → ${TUNNEL}/webhook/instagram"
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"instagram_register_webhook\",\"arguments\":{\"url\":\"${TUNNEL}/webhook/instagram\"}}}" \
  | python3 -m json.tool

echo
echo "Registering WhatsApp webhook → ${TUNNEL}/webhook/whatsapp"
call "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"whatsapp_register_webhook\",\"arguments\":{\"url\":\"${TUNNEL}/webhook/whatsapp\"}}}" \
  | python3 -m json.tool
