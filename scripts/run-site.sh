#!/usr/bin/env bash
# Builds and serves the static HappyCake website.
set -e
cd "$(dirname "$0")/../web"

if [[ ! -d node_modules ]]; then
  echo "Installing site dependencies..."
  npm install
fi

# Production preview by default; pass --dev for live-reload.
if [[ "${1:-}" == "--dev" ]]; then
  exec npm run dev
else
  npm run build
  exec npm run preview
fi
