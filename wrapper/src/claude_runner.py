"""Wrapper around `claude -p` headless invocation.

Runs Claude Code CLI with our system prompt + the customer message. Claude has
access to the sandbox MCP via the .mcp.json at the repo root, so it can call
square_*, kitchen_*, instagram_* tools mid-thought. We parse the JSON reply.
"""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from . import evidence
from .config import CATALOG_PATH, REPO_ROOT, SBC_TEAM_TOKEN

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


def _catalog_block() -> str:
    """Render an inline catalog table with the canonical variation_ids the agent must use."""
    cat = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = ["| variation_id | display | price | weight | category | notes |", "|---|---|---|---|---|---|"]
    for p in cat["products"]:
        notes = []
        if p.get("requires_owner_approval"):
            notes.append("requires owner approval")
        if p.get("lead_time_minutes"):
            notes.append(f"{p['lead_time_minutes']}-min lead")
        rows.append(
            f"| `{p['variation_id']}` | {p['display_name']} | ${p['price_usd']:.2f} | {p['weight']} | {p['category']} | {'; '.join(notes) or '—'} |"
        )
    return "\n".join(rows)


def _load_system_prompt() -> str:
    base = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return f"{base}\n\n## Live catalog (variation_ids to use in `items[*].variation_id`)\n\n{_catalog_block()}\n"


def _strip_fence(text: str) -> str:
    """Remove ```json ... ``` fencing if Claude included it despite instructions."""
    text = text.strip()
    fence = re.match(r"```(?:json)?\s*\n(.*?)\n```\s*$", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def run_claude(user_prompt: str, *, timeout: float = 90.0) -> str:
    """Invoke `claude -p` with our system prompt + the user prompt. Return raw stdout text."""
    system = _load_system_prompt()
    full_prompt = f"{system}\n\n---\n\nCustomer message:\n{user_prompt}"
    cmd = [
        "claude",
        "-p",
        "--output-format", "text",
        "--permission-mode", "bypassPermissions",
        full_prompt,
    ]
    env = {"SBC_TEAM_TOKEN": SBC_TEAM_TOKEN}
    import os
    env = {**os.environ, **env}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        evidence.log("error", "system", {"where": "claude_runner", "error": "timeout", "prompt": user_prompt[:200]})
        raise
    if proc.returncode != 0:
        evidence.log("error", "system", {
            "where": "claude_runner",
            "returncode": proc.returncode,
            "stderr": proc.stderr[:1000],
        })
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout


def respond_to_message(user_prompt: str, channel: str) -> dict[str, Any]:
    """Run the agent and parse the JSON decision. Always returns a dict.

    On parse failure, returns a fallback dict with intent='escalate'.
    """
    raw = run_claude(user_prompt)
    body = _strip_fence(raw)
    evidence.log("claude_call", channel, {"prompt": user_prompt[:500], "raw": raw[:1500]})
    try:
        decision = json.loads(body)
        if not isinstance(decision, dict):
            raise ValueError("not a JSON object")
        decision.setdefault("intent", "escalate")
        decision.setdefault("reply_text", "Let me get someone to help with this.")
        decision.setdefault("items", None)
        decision.setdefault("needs_owner_approval", False)
        decision.setdefault("rationale", "")
        return decision
    except (json.JSONDecodeError, ValueError) as e:
        evidence.log("error", "system", {"where": "json_parse", "error": str(e), "raw": raw[:1500]})
        return {
            "intent": "escalate",
            "reply_text": "Let me get someone from the team — back to you in a moment.",
            "items": None,
            "needs_owner_approval": True,
            "rationale": f"agent json parse failed: {e}",
        }
