"""High-level: customer message in → agent decides → side effects.

This is the orchestration layer that ties claude_runner, mcp_client, and
owner_bot together. Called from FastAPI route handlers.

Two paths for an order_intent decision:

1. **Auto-confirm** (preferred when feasible): the wrapper runs the same
   stock / ingredient checks the owner-approval branch runs, creates the
   Square order and kitchen ticket immediately, replaces `reply_text` with
   a real confirmation, and sends the owner an FYI Telegram message
   without approval buttons. The customer sees the confirmation in the
   same chat turn they ordered in.

2. **Owner card** (fallback): used when Claude flagged the order for
   approval, the catalog requires it (custom cake), the same-day counter
   is short, or the kitchen pantry can't cover the future-day bake.
"""
from __future__ import annotations
import secrets
from typing import Any

import yaml

from . import claude_runner, evidence, inventory, mcp_client, order_events, owner_bot
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
      - For an order_intent that passes stock/ingredient checks: creates
        the Square order + kitchen ticket immediately, replaces
        `reply_text` with the confirmation, sends an FYI to the owner.
      - For everything else that needs human review: sends a blocking
        approval card to the owner Telegram bot.
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

    # --- Path 1: auto-confirm a clean order in this same turn ----------
    if intent == "order_intent" and not needs_approval and decision.get("items"):
        order_id = f"hc_{secrets.token_hex(4)}"
        auto = await _attempt_auto_confirm(
            order_id=order_id,
            decision=decision,
            customer_name=customer_name,
            customer_handle=customer_handle,
            channel=channel,
            thread_id=thread_id,
            phone=phone,
        )
        if auto is not None:
            decision["reply_text"] = auto["confirmation_text"]
            decision["auto_confirmed"] = True
            decision["square_order_id"] = auto["square_order_id"]
            decision["order_id"] = order_id
            return decision
        # fall through to the owner-card path if auto-confirm couldn't fire

    # --- Path 2: owner card (custom cake, ingredient short, complaint, escalate) ---
    if intent in ("order_intent", "complaint", "escalate") or needs_approval:
        order_id = order_id or f"hc_{secrets.token_hex(4)}"
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


async def _attempt_auto_confirm(
    *,
    order_id: str,
    decision: dict[str, Any],
    customer_name: str,
    customer_handle: str,
    channel: str,
    thread_id: str | None,
    phone: str | None,
) -> dict[str, Any] | None:
    """Run the same stock + ingredient gates the owner-approve branch runs,
    and if everything passes, commit the order to Square + kitchen now.

    Returns a dict {square_order_id, confirmation_text} on success, or None
    if the order needs a human (custom item, same-day stockout, ingredient
    deficit, or any sandbox failure)."""
    items = decision.get("items") or []
    if not items:
        return None

    # Defense in depth: block any catalog item the brand marks as
    # owner-approval-only (custom birthday cake, etc) — even if Claude
    # forgot to set needs_owner_approval.
    catalog_by_var = {p["variation_id"]: p for p in _load_catalog()["products"]}
    for it in items:
        prod = catalog_by_var.get(it.get("variation_id", ""))
        if prod and prod.get("requires_owner_approval"):
            return None

    pickup_iso = decision.get("pickup_time_iso")
    same_day = inventory.is_same_day(pickup_iso)

    if same_day:
        shortfalls = inventory.check_ready_stock(items)
        if shortfalls:
            evidence.log("auto_confirm_blocked", channel, {
                "order_id": order_id,
                "reason": "same_day_stockout",
                "shortfalls": inventory.to_jsonable(shortfalls),
            })
            return None
    else:
        ingredient_short = inventory.check_ingredient_feasibility(items)
        if ingredient_short:
            evidence.log("auto_confirm_blocked", channel, {
                "order_id": order_id,
                "reason": "ingredient_short",
                "shortfalls": inventory.to_jsonable(ingredient_short),
            })
            return None

    # All gates green. Commit the order.
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
            "customerName": customer_name or "Friend",
            "customerNote": decision.get("customer_note") or "",
        })
    except Exception as e:
        evidence.log("error", "system", {"where": "auto_confirm_create_order", "error": str(e)})
        return None

    order_obj = (order_resp or {}).get("order") if isinstance(order_resp, dict) else None
    square_order_id = (order_obj or {}).get("id")
    if not square_order_id:
        evidence.log("auto_confirm_blocked", channel, {
            "order_id": order_id,
            "reason": "no_square_order_id",
            "resp": str(order_resp)[:300],
        })
        return None

    # Future-day path: now that the order is real, draw down the pantry.
    if not same_day:
        needs = inventory.compute_ingredient_needs(items)
        if needs:
            try:
                drawdown = inventory.decrement_ingredients(needs)
                evidence.log("inventory_drawdown", channel, {
                    "order_id": order_id,
                    "square_order_id": square_order_id,
                    "needs": drawdown.needs,
                    "before": drawdown.before,
                    "after": drawdown.after,
                    "shortfalls": inventory.to_jsonable(drawdown.shortfalls),
                    "crossed": [c.name for c in drawdown.crossed],
                })
                if drawdown.crossed:
                    purchase = inventory.compute_purchase_list()
                    evidence.log("purchase_alert", "system", {
                        "order_id": order_id,
                        "items": [inventory.to_jsonable(p) for p in purchase],
                    })
                    try:
                        await owner_bot.send_purchase_alert(purchase, order_id)
                    except Exception as e:
                        evidence.log("error", "system", {"where": "auto_confirm_purchase_alert", "error": str(e)})
            except Exception as e:
                evidence.log("error", "system", {"where": "auto_confirm_drawdown", "error": str(e)})

    # Kitchen ticket
    try:
        kitchen_items = [
            {"productId": _kitchen_id(it["variation_id"]), "quantity": it.get("quantity", 1)}
            for it in items
        ]
        mcp_client.call("kitchen_create_ticket", {
            "orderId": square_order_id,
            "customerName": customer_name or "Friend",
            "items": kitchen_items,
            "requestedPickupAt": pickup_iso or "",
            "notes": decision.get("customer_note") or "",
        })
    except Exception as e:
        evidence.log("error", "system", {"where": "auto_confirm_kitchen_ticket", "error": str(e)})

    items_label = _format_items(items)
    confirmation_text = _auto_confirm_message(
        customer_name=customer_name,
        channel=channel,
        items_label=items_label,
        pickup_iso=pickup_iso,
        same_day=same_day,
    )

    evidence.log("auto_confirm", channel, {
        "order_id": order_id,
        "square_order_id": square_order_id,
        "items_label": items_label,
        "pickup_time": pickup_iso,
        "same_day": same_day,
    })

    # Publish to any SSE/polling subscribers (so /order-status/ pages update)
    await order_events.publish(order_id, {
        "status": "approved",
        "message": confirmation_text,
        "square_order_id": square_order_id,
        "items": items_label,
        "pickup_time": pickup_iso,
        "auto_confirmed": True,
    })

    # FYI to owner — no buttons, just a heads-up.
    try:
        import html
        e = html.escape
        fyi = (
            f"✅ <b>Auto-confirmed</b> — {e(channel)} · {e(customer_name or 'Friend')}\n"
            f"<b>Items:</b> {e(items_label)}\n"
            + (f"<b>Pickup:</b> {e(pickup_iso)}\n" if pickup_iso else "")
            + f"<i>Square:</i> <code>{e(square_order_id)}</code>"
        )
        await owner_bot.send_fyi(fyi)
    except Exception as e:
        evidence.log("error", "system", {"where": "auto_confirm_fyi", "error": str(e)})

    return {
        "square_order_id": square_order_id,
        "confirmation_text": confirmation_text,
    }


def _auto_confirm_message(
    *,
    customer_name: str,
    channel: str,
    items_label: str,
    pickup_iso: str | None,
    same_day: bool,
) -> str:
    """Customer-facing confirmation for an auto-confirmed order."""
    name = _friendly_name(customer_name)
    closing = _channel_closing(channel)
    if same_day:
        timing = "Ready at the counter — pop in any time we're open today."
    elif pickup_iso:
        timing = f"We've got it on the schedule for {pickup_iso}."
    else:
        timing = "We've got it on the schedule — we'll confirm the exact pickup window shortly."
    return f"Confirmed, {name} — {items_label}. {timing} {closing}"


async def on_owner_edit_message(order_id: str, text: str, handoff: dict[str, Any]) -> None:
    """Owner typed a follow-up after Edit. Relay to customer on their channel
    and publish to SSE/polling subscribers so the website widget shows it too."""
    await _reply_to_customer(handoff, text)
    await order_events.publish(order_id, {
        "status": "edit_followup",
        "message": text,
    })


async def on_owner_decision(order_id: str, verb: str, handoff: dict[str, Any]) -> None:
    """Owner pressed Approve/Edit/Reject. Drive side effects."""
    raw = handoff.get("raw_decision", {})
    channel = handoff.get("channel", "instagram")

    square_order_id: str | None = None

    if verb == "approve":
        items = raw.get("items") or []
        if items:
            # Stock-aware qualification BEFORE we create the POS order.
            pickup_iso = handoff.get("pickup_time") or raw.get("pickup_time_iso")
            same_day = inventory.is_same_day(pickup_iso)

            if same_day:
                # ── Same-day path: confirm against the live counter ────────
                shortfalls = inventory.check_ready_stock(items)
                if shortfalls:
                    sf_payload = inventory.to_jsonable(shortfalls)
                    evidence.log("inventory_shortfall", channel, {
                        "order_id": order_id,
                        "shortfalls": sf_payload,
                    })
                    msg = _stockout_message(handoff, shortfalls)
                    await _reply_to_customer(handoff, msg)
                    await order_events.publish(order_id, {
                        "status": "rejected",
                        "message": msg,
                        "reason": "same-day stock unavailable",
                    })
                    return
            else:
                # ── Future-day path: draw down ingredient stock ───────────
                needs = inventory.compute_ingredient_needs(items)
                if needs:
                    drawdown = inventory.decrement_ingredients(needs)
                    evidence.log("inventory_drawdown", channel, {
                        "order_id": order_id,
                        "needs": drawdown.needs,
                        "before": drawdown.before,
                        "after": drawdown.after,
                        "shortfalls": inventory.to_jsonable(drawdown.shortfalls),
                        "crossed": [c.name for c in drawdown.crossed],
                    })
                    if drawdown.crossed:
                        purchase = inventory.compute_purchase_list()
                        evidence.log("purchase_alert", "system", {
                            "order_id": order_id,
                            "items": [inventory.to_jsonable(p) for p in purchase],
                        })
                        try:
                            await owner_bot.send_purchase_alert(purchase, order_id)
                        except Exception as e:
                            evidence.log("error", "system", {
                                "where": "send_purchase_alert",
                                "error": str(e),
                            })

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


def _stockout_message(handoff: dict[str, Any], shortfalls: list) -> str:
    """Customer-facing message when a same-day order can't be filled."""
    name = _friendly_name(handoff.get("customer_name"))
    channel = handoff.get("channel", "website")
    closing = _channel_closing(channel)
    # Try to pull display names from the catalog via the items_label
    label = handoff.get("items_label") or "the order"
    return (
        f"So sorry, {name} — we're out of {label} for today's counter. "
        f"If you can flex to tomorrow we'll bake fresh, or we can swap to "
        f"another cake we have in. {closing}"
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
