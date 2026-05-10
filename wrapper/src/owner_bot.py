"""Owner Telegram bot — surfaces order handoffs and approve/edit/reject buttons.

Uses python-telegram-bot's Application as a long-running task inside the FastAPI
app's lifespan. Inline keyboards carry callback_data of the form `order:<verb>:<id>`.
"""
from __future__ import annotations
import asyncio
import html
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import time

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import evidence
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID

log = logging.getLogger("happycake.owner_bot")

# pending[order_id] = full handoff dict; resolved when the owner taps a button.
_pending: dict[str, dict[str, Any]] = {}
# After Edit: chat_id → {order_id, handoff, expires_at}. Next non-command text
# message from that chat is forwarded to the customer on their channel.
_pending_edits: dict[int, dict[str, Any]] = {}
EDIT_TIMEOUT_SECONDS = 600
# Callbacks fired when the owner approves/edits/rejects.
_decision_handlers: list[Callable[[str, str, dict[str, Any]], Awaitable[None]]] = []
# Callbacks fired when the owner sends a free-form edit message after tapping Edit.
_edit_message_handlers: list[Callable[[str, str, dict[str, Any]], Awaitable[None]]] = []


@dataclass
class Handoff:
    order_id: str
    customer_name: str
    customer_handle: str
    channel: str  # 'instagram' | 'whatsapp' | 'website'
    items_label: str  # human-readable "1× cake \"Honey\" whole 1.2 kg — $55"
    pickup_time: str | None
    notes: str | None
    raw_decision: dict[str, Any] = field(default_factory=dict)


def register_decision_handler(fn: Callable[[str, str, dict[str, Any]], Awaitable[None]]) -> None:
    """Register an async callback fired when owner clicks Approve/Edit/Reject.

    fn signature: (order_id, decision: 'approve'|'edit'|'reject', handoff: dict) -> None
    """
    _decision_handlers.append(fn)


def register_edit_message_handler(
    fn: Callable[[str, str, dict[str, Any]], Awaitable[None]],
) -> None:
    """Register an async callback fired when the owner sends a free-form edit
    message after tapping Edit.

    fn signature: (order_id, message_text, handoff: dict) -> None
    """
    _edit_message_handlers.append(fn)


def _format_card(h: Handoff) -> str:
    e = html.escape  # Telegram HTML mode is strict about <, >, &
    lines = [
        f"<b>New {e(h.channel)} order</b> — {e(h.customer_name)}",
        f"@{e(h.customer_handle)}",
        "",
        f"<b>Items:</b> {e(h.items_label)}",
    ]
    if h.pickup_time:
        lines.append(f"<b>Pickup:</b> {e(h.pickup_time)}")
    if h.notes:
        lines.append(f"<b>Notes:</b> {e(h.notes)}")
    lines.append(f"\n<i>Order ID:</i> <code>{e(h.order_id)}</code>")
    return "\n".join(lines)


def _keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"order:approve:{order_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"order:edit:{order_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"order:reject:{order_id}"),
        ]
    ])


_app: Application | None = None


def get_app() -> Application:
    global _app
    if _app is None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing — set it in .env")
        _app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start", _on_start))
        _app.add_handler(CommandHandler("help", _on_help))
        _app.add_handler(CommandHandler("today", _on_today))
        _app.add_handler(CommandHandler("menu", _on_menu))
        _app.add_handler(CommandHandler("report", _on_report))
        _app.add_handler(CommandHandler("post", _on_post))
        _app.add_handler(CommandHandler("purchase", _on_purchase))
        _app.add_handler(CommandHandler("restock", _on_restock))
        _app.add_handler(CallbackQueryHandler(_on_callback, pattern=r"^order:"))
        _app.add_handler(CallbackQueryHandler(_on_post_callback, pattern=r"^post:"))
        # Free-form text from the owner is treated as a follow-up after Edit.
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_text))
    return _app


async def send_fyi(text: str, *, parse_mode: str = "HTML") -> None:
    """Information-only Telegram message — no buttons, no pending state.
    Used for auto-confirmed orders where the agent already committed the
    order on the customer's behalf and the owner just needs to know."""
    if not TELEGRAM_OWNER_CHAT_ID:
        log.warning("TELEGRAM_OWNER_CHAT_ID empty — fyi skipped")
        return
    try:
        app = get_app()
        await app.bot.send_message(
            chat_id=TELEGRAM_OWNER_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
    except Exception as e:
        evidence.log("error", "system", {"where": "send_fyi", "error": str(e)})


async def send_handoff(h: Handoff) -> None:
    if not TELEGRAM_OWNER_CHAT_ID:
        log.warning("TELEGRAM_OWNER_CHAT_ID empty — handoff skipped")
        evidence.log("owner_handoff", h.channel, {"order_id": h.order_id, "skipped": "no_chat_id"})
        return
    _pending[h.order_id] = {
        "customer_name": h.customer_name,
        "customer_handle": h.customer_handle,
        "channel": h.channel,
        "items_label": h.items_label,
        "pickup_time": h.pickup_time,
        "notes": h.notes,
        "raw_decision": h.raw_decision,
    }
    app = get_app()
    await app.bot.send_message(
        chat_id=TELEGRAM_OWNER_CHAT_ID,
        text=_format_card(h),
        reply_markup=_keyboard(h.order_id),
        parse_mode="HTML",
    )
    evidence.log("owner_handoff", h.channel, {"order_id": h.order_id, "items": h.items_label})


async def _on_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "HappyCake owner bot is online. Approval cards from customers appear here.\n\n"
        "Commands:\n"
        "  /today  — pending order cards\n"
        "  /menu   — today's catalog with prices and inventory\n"
        "  /report — POS revenue, kitchen load, and lead funnel\n"
        "  /post <theme> — draft an Instagram post for your approval\n"
        "  /help   — this list"
    )


async def _on_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>HappyCake owner bot — commands</b>\n\n"
        "• <code>/today</code> — pending order cards\n"
        "• <code>/menu</code> — catalog with prices + live inventory + capacity\n"
        "• <code>/report</code> — POS revenue / kitchen load / lead funnel snapshot\n"
        "• <code>/post &lt;theme&gt;</code> — draft an Instagram post for your approval, e.g. <code>/post Friday bake batch</code>\n\n"
        "Tap ✅ Approve / ✏️ Edit / ❌ Reject on any order card. Edit asks you for a follow-up message that gets sent to the customer on their channel.",
        parse_mode="HTML",
    )


async def _on_menu(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the catalog with live inventory + capacity, pulled from sandbox."""
    from . import mcp_client
    try:
        cat = mcp_client.call("square_list_catalog", {"limit": 50}) or {}
        capacity = mcp_client.call("kitchen_get_capacity", {}) or {}
        items = cat.get("catalog", []) if isinstance(cat, dict) else []
        lines = ["<b>Today on the menu</b>"]
        for it in items:
            cents = it.get("priceCents", 0) / 100
            lines.append(f"• {it.get('name')} — ${cents:.2f} <i>({it.get('category')})</i>")
        if capacity:
            lines.append("")
            lines.append(
                f"<b>Kitchen:</b> {capacity.get('remainingCapacityMinutes',0)} min remaining "
                f"of {capacity.get('dailyCapacityMinutes',0)} (default lead "
                f"{capacity.get('defaultLeadTimeMinutes',45)} min · "
                f"{capacity.get('queuedTickets',0)} queued)"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Couldn't pull menu — {e}")


async def _on_report(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily-style summary: POS revenue, kitchen production, marketing funnel."""
    from . import mcp_client
    try:
        pos = mcp_client.call("square_get_pos_summary", {}) or {}
        kitchen = mcp_client.call("kitchen_get_production_summary", {}) or {}
        marketing_report = mcp_client.call("marketing_report_to_owner", {}) or {}
        evidence_summary = mcp_client.call("evaluator_get_evidence_summary", {}) or {}

        lines = ["<b>HappyCake — operator report</b>"]
        if pos:
            lines.append(
                f"\n<b>POS:</b> {pos.get('orders',{}).get('total','?')} orders · "
                f"${(pos.get('revenue',{}).get('totalCents',0)/100):.2f} revenue"
            ) if isinstance(pos.get('orders'), dict) else lines.append(f"\n<b>POS:</b> {html.escape(str(pos))[:200]}")
        if kitchen:
            byst = kitchen.get("byStatus", {}) or {}
            lines.append(
                f"\n<b>Kitchen:</b> {kitchen.get('tickets','?')} tickets · "
                f"{byst.get('queued',0)} queued · {byst.get('accepted',0)} accepted · "
                f"{byst.get('ready',0)} ready · {byst.get('rejected',0)} rejected · "
                f"{kitchen.get('usedPrepMinutes','?')} min used / "
                f"{kitchen.get('dailyCapacityMinutes','?')} cap"
            )
        if isinstance(marketing_report, dict):
            campaigns = marketing_report.get("campaigns") or marketing_report
            lines.append(f"\n<b>Marketing report:</b> {html.escape(str(campaigns))[:300]}")
        if isinstance(evidence_summary, dict):
            c = evidence_summary.get("counts") or {}
            lines.append(
                f"\n<b>Evidence counts:</b> orders {c.get('squareOrders','?')} · "
                f"tickets {c.get('kitchenTickets','?')} · WA in {c.get('whatsappInbound','?')} · "
                f"IG actions {c.get('instagramActions','?')} · campaigns {c.get('marketingCampaigns','?')} · leads {c.get('marketingLeads','?')}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Report failed — {e}")


async def _on_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/post <theme>` triggers the marketing creative pipeline."""
    args = ctx.args or []
    theme = " ".join(args).strip()
    if not theme:
        await update.message.reply_text("Usage: /post <theme>. Example: /post Friday bake batch")
        return
    from . import marketing as marketing_mod
    try:
        out = await marketing_mod.queue_for_owner_approval(theme=theme, audience="")
        await update.message.reply_text(
            f"Drafted post <code>{html.escape(out['scheduled_id'])}</code>. "
            f"Approval card incoming above.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"Couldn't draft post — {e}")


# ---------- Purchase / restock (kitchen ingredient flow) ----------

def _format_purchase_list(items, header: str) -> str:
    e = html.escape
    if not items:
        return "🛒 <b>Shopping list</b> — nothing pending. Pantry's healthy."
    lines = [f"🛒 <b>{e(header)}</b>", ""]
    total_packs = 0
    for p in items:
        total_packs += getattr(p, "qty", 0)
        hint = getattr(p, "supplier_hint", None)
        suffix = f" — <i>{e(hint)}</i>" if hint else ""
        pack_qty = getattr(p, "pack_qty", "") or ""
        pack_label = f"{pack_qty} {e(p.unit)}" if pack_qty else e(p.unit)
        lines.append(
            f"• <b>{e(p.name)}</b> — {p.qty}× {pack_label} pack"
            f" (currently {p.on_hand} / threshold {p.reorder_at}){suffix}"
        )
    lines.append("")
    lines.append("After your shopping run, tell me with:")
    lines.append("  <code>/restock &lt;ingredient&gt; &lt;qty in native unit&gt;</code>")
    lines.append("  e.g. <code>/restock butter 1000</code> for a 4-pack of 250 g.")
    return "\n".join(lines)


async def send_purchase_alert(items, trigger_order_id: str) -> None:
    """Push a structured shopping list to the owner. Called from agent.on_owner_decision
    when an ingredient drops below its reorder threshold during a future-day order draw."""
    if not TELEGRAM_OWNER_CHAT_ID:
        log.warning("TELEGRAM_OWNER_CHAT_ID empty — purchase alert skipped")
        return
    text = _format_purchase_list(
        items,
        f"Reorder triggered by {trigger_order_id}",
    )
    app = get_app()
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_OWNER_CHAT_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("send_purchase_alert failed: %s", e)
        evidence.log("error", "system", {"where": "send_purchase_alert", "error": str(e)})


async def _on_purchase(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/purchase` shows the current shopping list (anything below reorder_at)."""
    from . import inventory
    try:
        items = inventory.compute_purchase_list()
        text = _format_purchase_list(items, "Shopping list — current snapshot")
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"Couldn't read inventory — {e}")


async def _on_restock(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/restock <ingredient> <qty>` bumps on-hand after the owner's shopping run."""
    from . import inventory
    args = ctx.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: <code>/restock &lt;ingredient&gt; &lt;qty&gt;</code>\n"
            "Example: <code>/restock butter 1000</code>",
            parse_mode="HTML",
        )
        return
    name = args[0].strip().lower()
    try:
        qty = float(args[1])
    except ValueError:
        await update.message.reply_text(f"Couldn't parse qty '{args[1]}' as a number.")
        return
    res = inventory.restock(name, qty)
    if not res.get("ok"):
        avail = res.get("available", [])
        msg = res.get("error", "restock failed")
        if avail:
            msg += "\n\nKnown ingredients: " + ", ".join(avail)
        await update.message.reply_text(msg)
        return
    evidence.log("restock", "telegram", {"name": name, "qty": qty, "on_hand": res["on_hand"]})
    await update.message.reply_text(
        f"✅ <b>{html.escape(name)}</b> now at <b>{res['on_hand']} {res.get('unit','')}</b>. "
        f"Use <code>/purchase</code> to see what's still pending.",
        parse_mode="HTML",
    )


async def _on_today(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _pending:
        await update.message.reply_text("Nothing pending right now. We're caught up.")
        return
    e = html.escape
    lines = [f"<code>{e(oid)}</code> · {e(p['items_label'])}" for oid, p in _pending.items()]
    await update.message.reply_text("Pending:\n" + "\n".join(lines), parse_mode="HTML")


async def _on_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":", 2)
    if len(parts) != 3:
        return
    _, verb, order_id = parts
    handoff = _pending.pop(order_id, None)
    if not handoff:
        await q.edit_message_text(q.message.text + "\n\n· Already handled.")
        return
    icon = {"approve": "✅", "edit": "✏️", "reject": "❌"}.get(verb, "·")
    await q.edit_message_text(f"{q.message.text}\n\n{icon} {verb.capitalize()}ed")
    evidence.log("owner_decision", handoff["channel"], {"order_id": order_id, "decision": verb})

    # If Edit, arm the edit-followup state for THIS chat. Next plain text
    # from the owner gets forwarded to the customer.
    if verb == "edit" and q.message and q.message.chat_id is not None:
        _pending_edits[q.message.chat_id] = {
            "order_id": order_id,
            "handoff": handoff,
            "expires_at": time.time() + EDIT_TIMEOUT_SECONDS,
        }
        try:
            await q.message.reply_text(
                f"✏️ Reply to this message with what to send the customer for "
                f"<code>{order_id}</code>. I'll relay it on their channel. "
                f"(Times out in 10 min.)",
                parse_mode="HTML",
                reply_markup=ForceReply(selective=True),
            )
        except Exception as e:
            log.warning("edit follow-up prompt failed: %s", e)

    for fn in _decision_handlers:
        try:
            await fn(order_id, verb, handoff)
        except Exception as e:
            log.exception("decision handler raised: %s", e)
            evidence.log("error", "system", {"where": "owner_decision_handler", "error": str(e)})


_post_decision_handlers: list[Callable[[str, str], Awaitable[None]]] = []


def register_post_decision_handler(fn: Callable[[str, str], Awaitable[None]]) -> None:
    """Register an async callback fired when owner clicks ✅/❌ on a post draft."""
    _post_decision_handlers.append(fn)


async def _on_post_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":", 2)
    if len(parts) != 3:
        return
    _, verb, scheduled_id = parts
    icon = {"approve": "✅", "reject": "❌"}.get(verb, "·")
    try:
        cur = q.message.caption if q.message and q.message.caption else (q.message.text if q.message else "")
        if q.message and q.message.caption is not None:
            await q.edit_message_caption(caption=f"{cur}\n\n{icon} {verb.capitalize()}ed", parse_mode="HTML")
        elif q.message and q.message.text is not None:
            await q.edit_message_text(f"{cur}\n\n{icon} {verb.capitalize()}ed")
    except Exception as e:
        log.warning("edit post card failed: %s", e)
    for fn in _post_decision_handlers:
        try:
            await fn(scheduled_id, verb)
        except Exception as e:
            log.exception("post decision handler raised: %s", e)
            evidence.log("error", "system", {"where": "post_decision_handler", "error": str(e)})


async def _on_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner sent free-form text. If we just asked them for an edit follow-up
    on this chat, forward it to the customer; otherwise ignore politely."""
    if not update.message or not update.message.text:
        return
    chat_id = update.message.chat_id
    state = _pending_edits.get(chat_id)
    if not state or state.get("expires_at", 0) < time.time():
        _pending_edits.pop(chat_id, None)
        await update.message.reply_text(
            "I only forward messages right after you tap ✏️ Edit on a card. "
            "If you wanted to take an action, use /today to see pending orders."
        )
        return

    order_id = state["order_id"]
    handoff = state["handoff"]
    text = update.message.text.strip()
    # Clear state immediately to avoid double-forwards on retries.
    _pending_edits.pop(chat_id, None)

    evidence.log("owner_edit_message", handoff["channel"], {
        "order_id": order_id,
        "text_preview": text[:200],
    })

    # Acknowledge to the owner first.
    await update.message.reply_text(
        f"Sent to the customer on {handoff['channel']} for "
        f"<code>{order_id}</code>.",
        parse_mode="HTML",
    )

    for fn in _edit_message_handlers:
        try:
            await fn(order_id, text, handoff)
        except Exception as e:
            log.exception("edit message handler raised: %s", e)
            evidence.log("error", "system", {"where": "owner_edit_handler", "error": str(e)})


async def start_polling() -> None:
    """Start the bot's update polling. Call from FastAPI lifespan."""
    app = get_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)


async def stop_polling() -> None:
    if _app is None:
        return
    await _app.updater.stop()
    await _app.stop()
    await _app.shutdown()
