"""High-level: customer message in → agent decides → side effects.

This is the orchestration layer that ties claude_runner, mcp_client, and
owner_bot together. Called from FastAPI route handlers.
"""
from __future__ import annotations
import secrets
from typing import Any

import yaml

from . import claude_runner, evidence, mcp_client, order_events, owner_bot
from .config import CATALOG_PATH


def _load_catalog() -> dict[str, Any]:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def _format_items(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return "—"
    catalog = _load_catalog()
    by_var = {p["variation_id"]: p for p in catalog["products"]}
    parts: list[str] = []
    for it in items:
        prod = by_var.get(it.get("variation_id", ""))
        if prod:
            parts.append(f'{it.get("quantity", 1)}× {prod["display_name"]} — ${prod["price_usd"]:.2f}')
        else:
            unknown = it.get("variation_id", "")
            parts.append(f'{it.get("quantity", 1)}× [unrecognised variation: {unknown}]')
    return ", ".join(parts)


async def handle_customer_message(
    *,
    channel: str,
    customer_name: str,
    customer_handle: str,
    text: str,
    thread_id: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    """Process one inbound customer message. Returns the agent decision dict.

    Side effects:
      - Logs to evidence/log.jsonl
      - For order_intent or escalate, sends a Telegram card to the owner
      - Returns a dict the route can use to reply on the customer channel
    """
    evidence.log("webhook_in", channel, {
        "customer_name": customer_name,
        "customer_handle": customer_handle,
        "text": text,
        "thread_id": thread_id,
        "phone": phone,
    })

    decision = claude_runner.respond_to_message(text, channel)

    intent = decision.get("intent", "escalate")
    needs_approval = bool(decision.get("needs_owner_approval", False))

    order_id: str | None = None
    if intent in ("order_intent", "complaint", "escalate") or needs_approval:
        order_id = f"hc_{secrets.token_hex(4)}"
        items_label = _format_items(decision.get("items"))
        handoff = owner_bot.Handoff(
            order_id=order_id,
            customer_name=customer_name or "Friend",
            customer_handle=customer_handle or "(unknown)",
            channel=channel,
            items_label=items_label if decision.get("items") else f"({intent}) — {decision.get('reply_text','')[:80]}",
            pickup_time=decision.get("pickup_time_iso"),
            notes=decision.get("customer_note") or decision.get("rationale"),
            raw_decision={
                **decision,
                "thread_id": thread_id,
                "phone": phone,
                "customer_name": customer_name,
                "customer_handle": customer_handle,
            },
        )
        try:
            await owner_bot.send_handoff(handoff)
        except Exception as e:
            evidence.log("error", "system", {"where": "send_handoff", "error": str(e)})

    decision["order_id"] = order_id
    return decision


async def on_owner_decision(order_id: str, verb: str, handoff: dict[str, Any]) -> None:
    """Owner pressed Approve/Edit/Reject. Drive side effects."""
    raw = handoff.get("raw_decision", {})
    channel = handoff.get("channel", "instagram")

    square_order_id: str | None = None

    if verb == "approve":
        items = raw.get("items") or []
        if items:
            # Convert snake_case (agent / catalog convention) → camelCase (sandbox API)
            square_items = [
                {
                    "variationId": it["variation_id"],
                    "quantity": it.get("quantity", 1),
                    **({"note": it["note"]} if it.get("note") else {}),
                }
                for it in items
            ]
            try:
                order_resp = mcp_client.call("square_create_order", {
                    "items": square_items,
                    "source": channel,
                    "customerName": handoff.get("customer_name") or "Friend",
                    "customerNote": handoff.get("notes") or "",
                })
                # Response shape: { mode, order: { id, ... }, kitchenTool }
                order_obj = (order_resp or {}).get("order") if isinstance(order_resp, dict) else None
                square_order_id = (order_obj or {}).get("id")
                evidence.log("mcp_call", "system", {"tool": "square_create_order", "ok": True, "id": square_order_id})

                if square_order_id:
                    kitchen_items = [
                        {"productId": _kitchen_id(it["variation_id"]), "quantity": it.get("quantity", 1)}
                        for it in items
                    ]
                    mcp_client.call("kitchen_create_ticket", {
                        "orderId": square_order_id,
                        "customerName": handoff.get("customer_name") or "Friend",
                        "items": kitchen_items,
                        "requestedPickupAt": handoff.get("pickup_time") or "",
                        "notes": handoff.get("notes") or "",
                    })
            except Exception as e:
                evidence.log("error", "system", {"where": "approve_create_order", "error": str(e)})

        # Reply to the customer on their channel (IG/WA outbound) and also
        # publish to any SSE subscribers (website chat widget).
        approval_text = _approval_message(handoff)
        await _reply_to_customer(handoff, approval_text)
        await order_events.publish(order_id, {
            "status": "approved",
            "message": approval_text,
            "square_order_id": square_order_id,
            "items": handoff.get("items_label"),
            "pickup_time": handoff.get("pickup_time"),
        })

    elif verb == "reject":
        rejection_text = _rejection_message(handoff)
        await _reply_to_customer(handoff, rejection_text)
        await order_events.publish(order_id, {
            "status": "rejected",
            "message": rejection_text,
        })

    elif verb == "edit":
        edit_text = "Quick check — the team's reviewing one detail and will be back to you shortly. Thanks for your patience."
        await _reply_to_customer(handoff, edit_text)
        await order_events.publish(order_id, {
            "status": "edit",
            "message": edit_text,
        })


def _kitchen_id(variation_id: str) -> str:
    catalog = _load_catalog()
    for p in catalog["products"]:
        if p["variation_id"] == variation_id:
            return p["kitchen_product_id"]
    return variation_id


def _friendly_name(raw_name: str | None) -> str:
    """Best-effort first name. Skip placeholder names like 'Site visitor'."""
    if not raw_name:
        return "friend"
    placeholders = {"site", "site visitor", "friend", "anonymous", "(unknown)", "guest"}
    if raw_name.lower().strip() in placeholders:
        return "friend"
    return raw_name.split()[0]


def _is_real_order(raw: dict[str, Any]) -> bool:
    """An 'order' handoff has actual items; escalations/FAQs/complaints don't."""
    return bool(raw.get("items"))


def _channel_closing(channel: str) -> str:
    """The brandbook closing — but only when the customer is on a channel that
    can act on it. The website chat widget IS the channel; pointing them
    elsewhere is silly."""
    if channel == "website":
        return "Reply here if anything changes."
    if channel == "instagram":
        return "Order on the site at happycake.us or send us a message on WhatsApp."
    if channel == "whatsapp":
        return "Order on the site at happycake.us — or stay on WhatsApp and we'll take it from here."
    return "Order on the site at happycake.us or send a message on WhatsApp."


def _approval_message(handoff: dict[str, Any]) -> str:
    raw = handoff.get("raw_decision", {}) or {}
    name = _friendly_name(handoff.get("customer_name"))
    channel = handoff.get("channel", "website")
    closing = _channel_closing(channel)

    if _is_real_order(raw):
        items = handoff.get("items_label", "")
        pickup = handoff.get("pickup_time")
        parts = [f"Confirmed, {name} — {items}."]
        if pickup:
            parts.append(f"Ready by {pickup}.")
        parts.append(closing)
        return " ".join(parts)

    # No items — escalation/complaint that the owner has acknowledged.
    return (
        f"Got it, {name} — the team has it. We'll be back to you here as soon "
        f"as there's an answer. {closing}"
    )


def _rejection_message(handoff: dict[str, Any]) -> str:
    raw = handoff.get("raw_decision", {}) or {}
    name = _friendly_name(handoff.get("customer_name"))
    channel = handoff.get("channel", "website")
    closing = _channel_closing(channel)
    if _is_real_order(raw):
        return (
            f"Sorry, {name} — we can't fit this one in. "
            f"If you can flex the date or size, tell us here and we'll try again. {closing}"
        )
    return (
        f"Thanks, {name} — we won't be able to help on this one. {closing}"
    )


async def _reply_to_customer(handoff: dict[str, Any], text: str) -> None:
    channel = handoff.get("channel")
    raw = handoff.get("raw_decision", {})
    try:
        if channel == "instagram":
            thread_id = raw.get("thread_id")
            if thread_id:
                mcp_client.call("instagram_send_dm", {"threadId": thread_id, "message": text})
        elif channel == "whatsapp":
            phone = raw.get("phone")
            if phone:
                mcp_client.call("whatsapp_send", {"to": phone, "message": text})
        # website channel: no outbound; the chat widget got the reply already in the initial decision
        evidence.log("customer_reply", channel or "unknown", {"text": text[:300]})
    except Exception as e:
        evidence.log("error", "system", {"where": "reply_to_customer", "error": str(e)})
