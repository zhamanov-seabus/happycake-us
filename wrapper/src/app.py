"""FastAPI app — webhook receivers + on-site chat + Telegram owner bot."""
from __future__ import annotations
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import agent, evidence, order_events, owner_bot
from .config import PUBLIC_TUNNEL_URL, TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("happycake.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the owner-decision callback before polling starts
    owner_bot.register_decision_handler(agent.on_owner_decision)
    polling_task = None
    if TELEGRAM_BOT_TOKEN:
        try:
            await owner_bot.start_polling()
            log.info("Owner bot polling started")
        except Exception as e:
            log.exception("Owner bot failed to start: %s", e)
    else:
        log.warning("TELEGRAM_BOT_TOKEN missing — owner bot disabled")
    try:
        yield
    finally:
        if TELEGRAM_BOT_TOKEN:
            try:
                await owner_bot.stop_polling()
            except Exception as e:
                log.warning("Owner bot stop raised: %s", e)


app = FastAPI(title="HappyCake wrapper", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "tunnel": PUBLIC_TUNNEL_URL or None}


# ---------- Lead capture ----------

class LeadIn(BaseModel):
    email: str
    name: str | None = None
    intent: str | None = None  # 'friday-batch', 'whole-cakes', etc.


@app.post("/lead")
async def lead(payload: LeadIn) -> dict:
    """Capture an email signup. Stored in evidence/leads.jsonl for the
    operator/marketing agent to follow up on. Lightweight email validation."""
    email = (payload.email or "").strip()
    if "@" not in email or len(email) > 254:
        return {"ok": False, "error": "invalid email"}
    evidence.log("lead_capture", "website", {
        "email": email,
        "name": (payload.name or "").strip()[:80],
        "intent": (payload.intent or "friday-batch").strip()[:40],
    })
    return {"ok": True, "message": "Got it — we'll send a heads-up before each Friday batch."}


# ---------- On-site chat ----------

class ChatIn(BaseModel):
    message: str
    visitor_id: str | None = None


class ChatOut(BaseModel):
    reply: str
    intent: str
    needs_owner_approval: bool
    order_id: str | None = None


@app.post("/chat", response_model=ChatOut)
async def chat(payload: ChatIn) -> ChatOut:
    decision = await agent.handle_customer_message(
        channel="website",
        customer_name="Site visitor",
        customer_handle=payload.visitor_id or "anonymous",
        text=payload.message,
    )
    return ChatOut(
        reply=decision.get("reply_text") or "Thanks — let me get back to you on WhatsApp.",
        intent=decision.get("intent", "escalate"),
        needs_owner_approval=bool(decision.get("needs_owner_approval", False)),
        order_id=decision.get("order_id"),
    )


# ---------- Server-sent events: live order status ----------
# Browser opens an EventSource here; we stream status changes as the owner
# acts. Times out heartbeat every 25 s so proxies don't kill the connection.

# Short-polling: returns the latest known state for an order, plus the
# entire publish history. The website chat widget polls this every 2 s.
# (SSE is implemented but Cloudflare quick tunnels buffer it indefinitely;
# polling works through any proxy.)

@app.get("/order/{order_id}")
async def order_status(order_id: str) -> dict:
    """Wrapper-side state for an order_id. Used by the chat widget polling
    and the /order-status/ page on the static site. If the order_id looks
    like a Square POS id (starts with sq_order_), also fetch the live
    sandbox state so the customer sees kitchen progress."""
    state = order_events.get_state(order_id)
    history = order_events.get_history(order_id)

    sandbox: dict | None = None
    if order_id.startswith("sq_order_"):
        try:
            from . import mcp_client
            recent = mcp_client.call("square_recent_orders", {"limit": 50}) or {}
            orders = recent.get("orders", []) if isinstance(recent, dict) else []
            match = next((o for o in orders if o.get("id") == order_id), None)
            if match:
                tickets = mcp_client.call("kitchen_list_tickets", {}) or []
                ticket = next((t for t in tickets if t.get("orderId") == order_id), None)
                sandbox = {"order": match, "ticket": ticket}
        except Exception as e:
            evidence.log("error", "system", {"where": "order_status_sandbox_lookup", "error": str(e)})

    return {
        "order_id": order_id,
        "status": (state or {}).get("status", "pending_owner"),
        "latest": state,
        "history": history,
        "sandbox": sandbox,
    }


@app.get("/order/{order_id}/events")
async def order_status_stream(order_id: str) -> StreamingResponse:
    """SSE alternative — kept for clients on proxies that don't buffer."""
    async def gen():
        q = await order_events.subscribe(order_id)
        try:
            yield ":" + (" " * 2048) + "\n\n"
            yield f"event: open\ndata: {json.dumps({'order_id': order_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: status\ndata: {json.dumps(event)}\n\n"
                if event.get("status") in ("approved", "rejected"):
                    break
        finally:
            order_events.unsubscribe(order_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------- Webhook payload extraction ----------
# The sandbox forwards events using Meta's webhook envelope:
#   {object, entry: [{changes: [{field, value: {messages, contacts, ...}}]}]}
# Our own scripts/demo.sh uses a flat shape:
#   {from, fromName, message, threadId, ...}
# This extractor handles both so the channel handlers stay simple.

def _extract_message(channel: str, payload: dict) -> dict:
    """Return {text, from, fromName, threadId} or {} if no usable message."""
    # Flat shape (our scripts) takes precedence if present
    text = payload.get("message") or payload.get("text") or payload.get("body")
    if text:
        return {
            "text": text,
            "from": payload.get("from") or payload.get("fromHandle"),
            "fromName": payload.get("fromName") or payload.get("from"),
            "threadId": payload.get("threadId"),
        }

    # Meta envelope — walk entry[*].changes[*].value.messages[*]
    try:
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                contacts = value.get("contacts") or []
                msgs = value.get("messages") or []
                for m in msgs:
                    body = (m.get("text") or {}).get("body")
                    if not body:
                        continue
                    sender = m.get("from")
                    name = None
                    if contacts:
                        c0 = contacts[0] or {}
                        name = (c0.get("profile") or {}).get("name") or c0.get("wa_id")
                    return {
                        "text": body,
                        "from": sender,
                        "fromName": name or sender,
                        # IG uses thread_id; WA threads keyed off phone for our purposes
                        "threadId": m.get("threadId") or value.get("threadId"),
                    }
    except (TypeError, AttributeError):
        pass

    return {}


# ---------- Instagram webhook ----------

@app.post("/webhook/instagram")
async def webhook_instagram(payload: dict) -> dict:
    evidence.log("webhook_in", "instagram", {"payload": payload})
    extracted = _extract_message("instagram", payload)
    msg = extracted.get("text") or ""
    if not msg:
        return {"ok": True, "skipped": "no message", "shape_seen": list(payload.keys())[:6]}
    decision = await agent.handle_customer_message(
        channel="instagram",
        customer_name=extracted.get("fromName") or "Friend",
        customer_handle=extracted.get("from") or "ig_user",
        text=msg,
        thread_id=extracted.get("threadId"),
    )
    if decision.get("intent") in ("faq", "smalltalk") and not decision.get("needs_owner_approval"):
        thread_id = extracted.get("threadId")
        if thread_id:
            from . import mcp_client
            try:
                mcp_client.call("instagram_send_dm", {
                    "threadId": thread_id,
                    "message": decision.get("reply_text", "Thanks — back to you shortly."),
                })
                evidence.log("customer_reply", "instagram", {"text": decision.get("reply_text", "")[:300]})
            except Exception as e:
                evidence.log("error", "system", {"where": "ig_inline_reply", "error": str(e)})
    return {"ok": True, "intent": decision.get("intent")}


# ---------- WhatsApp webhook ----------

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict) -> dict:
    evidence.log("webhook_in", "whatsapp", {"payload": payload})
    extracted = _extract_message("whatsapp", payload)
    msg = extracted.get("text") or ""
    if not msg:
        return {"ok": True, "skipped": "no message", "shape_seen": list(payload.keys())[:6]}
    phone = extracted.get("from")
    decision = await agent.handle_customer_message(
        channel="whatsapp",
        customer_name=extracted.get("fromName") or "Friend",
        customer_handle=phone or "wa_user",
        text=msg,
        phone=phone,
    )
    if decision.get("intent") in ("faq", "smalltalk") and not decision.get("needs_owner_approval"):
        if phone:
            from . import mcp_client
            try:
                mcp_client.call("whatsapp_send", {
                    "to": phone,
                    "message": decision.get("reply_text", "Thanks — back to you shortly."),
                })
                evidence.log("customer_reply", "whatsapp", {"text": decision.get("reply_text", "")[:300]})
            except Exception as e:
                evidence.log("error", "system", {"where": "wa_inline_reply", "error": str(e)})
    return {"ok": True, "intent": decision.get("intent")}
