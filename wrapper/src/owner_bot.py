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
        _app.add_handler(CommandHandler("today", _on_today))
        _app.add_handler(CallbackQueryHandler(_on_callback, pattern=r"^order:"))
        # Free-form text from the owner is treated as a follow-up after Edit.
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_text))
    return _app


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
        "HappyCake owner bot is online. Approval cards from customers will appear here.\n"
        "Use /today to see what's queued."
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
