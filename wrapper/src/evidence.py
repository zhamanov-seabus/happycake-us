"""Append-only structured evidence log. Every meaningful event gets one line.

Schema (one JSON object per line):
  ts:       ISO 8601 UTC timestamp
  type:     "webhook_in" | "claude_call" | "mcp_call" | "owner_handoff" |
            "owner_decision" | "customer_reply" | "error" | "demo_step"
  source:   "instagram" | "whatsapp" | "website" | "telegram" | "system"
  payload:  arbitrary structured data
"""
from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from typing import Any

from .config import EVIDENCE_PATH

_lock = threading.Lock()


def log(event_type: str, source: str, payload: dict[str, Any] | None = None) -> None:
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "source": source,
        "payload": payload or {},
    }
    with _lock:
        with EVIDENCE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
