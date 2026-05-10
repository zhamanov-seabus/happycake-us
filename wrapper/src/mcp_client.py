"""Direct HTTP client for the Steppe Business Club sandbox MCP server.

Most agent-side calls go through `claude -p` (which uses .mcp.json). This client
exists for: (1) wrapper-side calls that don't need a model (e.g. registering a
webhook on boot), and (2) deterministic tool calls inside test scripts.
"""
from __future__ import annotations
import json
from typing import Any

import httpx

from . import evidence
from .config import SBC_MCP_URL, SBC_TEAM_TOKEN


class MCPError(RuntimeError):
    pass


def call(tool: str, arguments: dict[str, Any] | None = None, *, timeout: float = 30.0) -> Any:
    """Call a sandbox tool. Returns parsed JSON of the inner content text or raw structure."""
    if not SBC_TEAM_TOKEN:
        raise MCPError("SBC_TEAM_TOKEN is empty — set it in .env")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Team-Token": SBC_TEAM_TOKEN,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(SBC_MCP_URL, json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        evidence.log("error", "system", {"tool": tool, "error": data["error"], "args": arguments})
        raise MCPError(f"MCP error from {tool}: {data['error']}")
    result = data.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list) and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            parsed = json.loads(text)
            evidence.log("mcp_call", "system", {"tool": tool, "args": arguments, "ok": True})
            return parsed
        except json.JSONDecodeError:
            evidence.log("mcp_call", "system", {"tool": tool, "args": arguments, "ok": True, "raw": True})
            return text
    evidence.log("mcp_call", "system", {"tool": tool, "args": arguments, "ok": True, "shape": "structured"})
    return result


def list_tools() -> list[dict[str, Any]]:
    """Return the list of available tool descriptors."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Team-Token": SBC_TEAM_TOKEN,
    }
    with httpx.Client(timeout=15.0) as client:
        r = client.post(SBC_MCP_URL, json=body, headers=headers)
    r.raise_for_status()
    return r.json().get("result", {}).get("tools", [])
