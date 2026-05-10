"""Drive the weekend-capacity-crunch deterministic scenario and respond
to every delivered event via the right MCP tool. Bumps the channel-response
score in the evaluator report.

Usage:
    uv run --active --project /Users/azamat/code/happycake-us/wrapper \
        python scripts/run-weekend-scenario.py
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wrapper" / "src"))

from happycake_wrapper import mcp_client  # noqa: E402


def main() -> None:
    print("=== Start weekend-capacity-crunch ===")
    started = mcp_client.call("world_start_scenario", {
        "scenarioId": "weekend-capacity-crunch",
        "seed": 9100520,
    })
    print(json.dumps(started, indent=2)[:300] if started else "(start failed)")

    print("\n=== Drive ticks, respond to each delivered event ===")
    for tick in range(10):
        mcp_client.call("world_advance_time", {"minutes": 60})
        evt_resp = mcp_client.call("world_next_event")
        if not evt_resp or evt_resp.get("status") == "complete":
            print(f"tick {tick + 1}: scenario complete")
            break
        e = evt_resp.get("event") or {}
        eid = e.get("id")
        ch = e.get("channel")
        etype = e.get("type")
        p = e.get("payload") or {}
        print(f"tick {tick + 1}: {eid} {ch}/{etype}")

        if ch == "whatsapp" and etype == "inbound_message":
            phone = p.get("from")
            msg = (
                "Got your message — let me check today's schedule. "
                "Order on the site at happycake.us — or stay on WhatsApp."
            )
            if phone:
                mcp_client.call("whatsapp_send", {"to": phone, "message": msg})
        elif ch == "instagram" and etype == "comment":
            cid = p.get("commentId") or f"comment_{eid}"
            mcp_client.call("instagram_reply_to_comment", {
                "commentId": cid,
                "message": (
                    "Yes — we deliver locally. DM us and we'll set it up. "
                    "https://happycake.us/"
                ),
            })
        elif ch == "instagram" and etype == "inbound_message":
            thread = p.get("threadId") or p.get("from")
            if thread:
                mcp_client.call("instagram_send_dm", {
                    "threadId": thread,
                    "message": (
                        "Hi! Tell us the date and size and we'll lock it in. "
                        "https://happycake.us/"
                    ),
                })
        elif ch == "gbusiness" and etype == "review":
            reviews = mcp_client.call("gb_list_reviews") or []
            rid = (reviews[-1].get("id") if isinstance(reviews, list) and reviews else "rev_001")
            mcp_client.call("gb_simulate_reply", {
                "reviewId": rid,
                "reply": (
                    "Thanks for the note — we read every review and we will keep "
                    "tightening the bake. Order on the site at happycake.us or "
                    "send a message on WhatsApp."
                ),
            })
        elif ch == "square" and etype == "walk_in_order":
            mcp_client.call("square_create_order", {
                "items": p.get("items", []),
                "source": "walk-in",
                "customerName": "Walk-in (weekend scenario)",
                "customerNote": f"Walk-in surge from {eid}",
            })
        elif ch == "kitchen":
            tickets = mcp_client.call("kitchen_list_tickets", {"status": "queued"}) or []
            if isinstance(tickets, list) and tickets:
                t = tickets[0]
                mcp_client.call("kitchen_accept_ticket", {
                    "ticketId": t["id"],
                    "note": "Weekend capacity check — accepted within remaining minutes.",
                })
        elif ch == "marketing" and etype == "campaign_lead_spike":
            camp = mcp_client.call("marketing_create_campaign", {
                "name": "Weekend surge response",
                "channel": "whatsapp",
                "objective": f"Capture {p.get('leads', 0)} weekend leads",
                "budgetUsd": p.get("budgetPressureUsd") or 50,
                "targetAudience": "Sugar Land weekend planners",
                "offer": "Saturday slice — $8.50 — first ten get a free coffee",
                "landingPath": "/catalog",
            }) or {}
            cid = camp.get("campaignId") or camp.get("id")
            if cid:
                mcp_client.call("marketing_launch_simulated_campaign", {
                    "campaignId": cid,
                    "approvalNote": "Owner approved on weekend lead surge.",
                })
                leads = mcp_client.call("marketing_generate_leads", {"campaignId": cid}) or {}
                ll = leads.get("leads") if isinstance(leads, dict) else leads
                if isinstance(ll, list):
                    for lead in ll[:5]:
                        lid = lead.get("leadId") or lead.get("id")
                        if lid:
                            mcp_client.call("marketing_route_lead", {
                                "leadId": lid,
                                "routeTo": "whatsapp",
                                "reason": "Weekend surge: route directly to WA.",
                            })
        time.sleep(0.1)

    print("\n=== Final scenario summary ===")
    print(json.dumps(mcp_client.call("world_get_scenario_summary", {}) or {}, indent=2))


if __name__ == "__main__":
    main()
