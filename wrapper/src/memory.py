"""Customer memory — per-handle order history so returning customers get recognized.

Lightweight, file-based (data/customer_memory.jsonl). Each line is one event:
  {"ts": ..., "key": "<channel>:<handle_or_phone>", "type": "order"|"note",
   "customer_name": "Maria", "channel": "instagram",
   "items_label": "1× cake \"Honey\" whole 1.2 kg", "pickup_time": "...",
   "notes": "...", "order_id": "hc_..."}

Key derivation:
  - WhatsApp:  "whatsapp:+15551234567"
  - Instagram: "instagram:<thread_id>"
  - Website:   "website:<customer_name_lower>" (best-effort; site visitors
               are anonymous unless they self-identify)

Recall returns:
  {
    "first_seen": "2026-04-01T10:00:00Z",
    "order_count": 3,
    "last_order": {... most recent order event ...},
    "recent_orders": [last 5 order events],
    "preferred_items": ["sq_var_whole_honey_cake", ...],  # top-2 by frequency
    "notes": [free-form notes joined with " | "],
  }

Privacy: no payment data, no addresses. Just commerce-relevant signals.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

MEMORY_PATH = REPO_ROOT / "data" / "customer_memory.jsonl"
RECENT_LIMIT = 5


_PLACEHOLDER_NAMES = {"site visitor", "site", "anonymous", "friend", "guest", "(unknown)", ""}


def _key(*, channel: str, handle: str | None, phone: str | None, customer_name: str | None) -> str | None:
    """Derive a stable key from whatever identifier we have for this customer.
    Prefer durable IDs (phone, IG thread, browser visitor_id) over names —
    names drift, placeholders ('Site visitor') collide across all anonymous
    visitors, and the same person can self-introduce differently."""
    if channel == "whatsapp" and phone:
        return f"whatsapp:{phone.strip()}"
    if channel == "instagram" and handle:
        return f"instagram:{handle.strip()}"
    if channel == "website" and handle and handle.strip().lower() not in {"anonymous", ""}:
        return f"website:{handle.strip()}"
    # Fall back to a name slug, but only if it's a real name — placeholder
    # routes ("Site visitor") collide across customers and would corrupt memory.
    if customer_name and customer_name.strip().lower() not in _PLACEHOLDER_NAMES:
        slug = re.sub(r"[^a-z0-9]+", "-", customer_name.lower()).strip("-")
        if slug:
            return f"{channel}:name:{slug}"
    if handle:
        return f"{channel}:{handle.strip()}"
    if phone:
        return f"{channel}:{phone.strip()}"
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_order(
    *,
    channel: str,
    customer_name: str | None,
    handle: str | None,
    phone: str | None,
    items_label: str,
    pickup_time: str | None,
    notes: str | None,
    order_id: str,
    items: list[dict[str, Any]] | None = None,
) -> None:
    """Append an order event to the customer's memory file."""
    key = _key(channel=channel, handle=handle, phone=phone, customer_name=customer_name)
    if not key:
        return
    row = {
        "ts": _now(),
        "key": key,
        "type": "order",
        "customer_name": (customer_name or "").strip() or None,
        "channel": channel,
        "items_label": items_label,
        "items": items or [],
        "pickup_time": pickup_time,
        "notes": notes,
        "order_id": order_id,
    }
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MEMORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # Memory is enrichment, never load-bearing — failures should not break order flow.
        pass


def record_note(
    *,
    channel: str,
    customer_name: str | None,
    handle: str | None,
    phone: str | None,
    note: str,
) -> None:
    key = _key(channel=channel, handle=handle, phone=phone, customer_name=customer_name)
    if not key:
        return
    row = {
        "ts": _now(),
        "key": key,
        "type": "note",
        "customer_name": (customer_name or "").strip() or None,
        "channel": channel,
        "note": note,
    }
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MEMORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recall(
    *,
    channel: str,
    handle: str | None = None,
    phone: str | None = None,
    customer_name: str | None = None,
) -> dict[str, Any] | None:
    """Return the customer's history if any. None for first-time customers."""
    key = _key(channel=channel, handle=handle, phone=phone, customer_name=customer_name)
    if not key or not MEMORY_PATH.exists():
        return None

    rows: list[dict[str, Any]] = []
    try:
        with MEMORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("key") == key:
                    rows.append(r)
    except Exception:
        return None

    if not rows:
        return None

    rows.sort(key=lambda r: r.get("ts") or "")
    orders = [r for r in rows if r.get("type") == "order"]
    notes = [r.get("note") for r in rows if r.get("type") == "note" and r.get("note")]

    item_counter: Counter = Counter()
    for r in orders:
        for it in (r.get("items") or []):
            vid = it.get("variation_id")
            if vid:
                item_counter[vid] += int(it.get("quantity") or 1)

    return {
        "key": key,
        "first_seen": rows[0].get("ts"),
        "order_count": len(orders),
        "last_order": orders[-1] if orders else None,
        "recent_orders": orders[-RECENT_LIMIT:],
        "preferred_items": [vid for vid, _ in item_counter.most_common(2)],
        "notes": notes,
        "customer_name": next((r.get("customer_name") for r in reversed(rows) if r.get("customer_name")), None),
    }


def summary_for_prompt(rec: dict[str, Any] | None) -> str:
    """Render the recalled record as a compact block the agent reads.
    Empty string for first-time customers (no block injected)."""
    if not rec or not rec.get("order_count"):
        return ""

    name = rec.get("customer_name") or "(name not on file)"
    last = rec.get("last_order") or {}
    last_label = (last.get("items_label") or "—").strip()
    last_time = (last.get("pickup_time") or last.get("ts") or "—")
    pref_ids = rec.get("preferred_items") or []
    pref_str = ", ".join(pref_ids) if pref_ids else "—"
    note_str = " | ".join(rec.get("notes") or []) or "—"

    return (
        "## Returning customer (memory)\n\n"
        f"- Name on file: **{name}**\n"
        f"- Order count: {rec.get('order_count')}\n"
        f"- Last order: {last_label}\n"
        f"- Last pickup: {last_time}\n"
        f"- Preferred variations: `{pref_str}`\n"
        f"- Notes: {note_str}\n\n"
        "Greet warmly, mention something specific from history if it fits naturally "
        "(e.g. 'the usual?', 'the whole honey cake again?'). Don't recite the list — "
        "be conversational. If they say 'the usual' without details, propose the most "
        "frequent past item and confirm.\n"
    )
