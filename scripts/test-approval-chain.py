"""Standalone test: simulate the owner clicking 'Approve' to verify the
sandbox MCP write-path (square_create_order + kitchen_create_ticket).

Run from the repo root: uv run --active python scripts/test-approval-chain.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wrapper" / "src"))

import asyncio  # noqa: E402

import happycake_wrapper.agent as agent  # noqa: E402
from happycake_wrapper import mcp_client  # noqa: E402


async def main() -> None:
    fake_handoff = {
        "customer_name": "Maria Lopez (test)",
        "customer_handle": "maria_lopez_demo",
        "channel": "instagram",
        "items_label": '1× cake "Honey" — whole — $55.00',
        "pickup_time": "2026-05-09T15:00:00",
        "notes": "Test order from approval-chain script",
        "raw_decision": {
            "intent": "order_intent",
            "items": [
                {"variation_id": "sq_var_whole_honey_cake", "quantity": 1, "note": "test"}
            ],
            "thread_id": "ig_demo_thread_001",
            "customer_name": "Maria Lopez (test)",
            "customer_handle": "maria_lopez_demo",
        },
    }
    print("Simulating owner approval...")
    await agent.on_owner_decision("hc_test123", "approve", fake_handoff)
    print("Done. Now polling sandbox for the order:")

    recent = mcp_client.call("square_recent_orders", {"limit": 3})
    print(recent)
    print()
    print("Kitchen tickets:")
    tickets = mcp_client.call("kitchen_list_tickets", {})
    print(tickets)


asyncio.run(main())
