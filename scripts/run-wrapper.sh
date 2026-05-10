#!/usr/bin/env bash
# Boots the FastAPI wrapper service. Reads .env from the repo root.
set -e
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env found — copy .env.example to .env and fill in your tokens." >&2
  exit 1
fi

cd wrapper
exec uv run --active uvicorn happycake_wrapper.app:app \
  --host "${WRAPPER_HOST:-0.0.0.0}" \
  --port "${WRAPPER_PORT:-8000}" \
  --reload
