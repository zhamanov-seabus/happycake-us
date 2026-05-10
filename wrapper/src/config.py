"""Centralised env config. Loads .env from the repo root if present."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var {key}. Copy .env.example to .env and fill in.")
    return val or ""


SBC_TEAM_TOKEN = _env("SBC_TEAM_TOKEN")
SBC_MCP_URL = _env("SBC_MCP_URL", "https://www.steppebusinessclub.com/api/mcp")
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = _env("TELEGRAM_OWNER_CHAT_ID")
PUBLIC_TUNNEL_URL = _env("PUBLIC_TUNNEL_URL")
WRAPPER_PORT = int(_env("WRAPPER_PORT", "8000"))
PUBLIC_SITE_URL = _env("PUBLIC_SITE_URL", "https://happycake.us")

CATALOG_PATH = REPO_ROOT / "data" / "catalog.yml"
BRANDBOOK_PATH = REPO_ROOT / "data" / "brandbook.md"
EVIDENCE_PATH = REPO_ROOT / "evidence" / "log.jsonl"
EVIDENCE_PATH.parent.mkdir(exist_ok=True)
