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

@app.get("/order/{order_id}/events")
async def order_status_stream(order_id: str) -> StreamingResponse:
    async def gen():
        q = await order_events.subscribe(order_id)
        try:
            yield f"event: open\ndata: {json.dumps({'order_id': order_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: status\ndata: {json.dumps(event)}\n\n"
                if event.get("status") in ("approved", "rejected"):
                    # Terminal states — close the stream.
                    break
        finally:
            order_events.unsubscribe(order_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- Instagram webhook ----------
# The sandbox forwards events here after we register via instagram_register_webhook.
# Shape: { "type": "dm.in", "threadId": "...", "from": "...", "fromName": "...", "message": "..." }
# We accept a permissive payload — the sandbox forwarder may use slightly different keys.

@app.post("/webhook/instagram")
async def webhook_instagram(payload: dict) -> dict:
    evidence.log("webhook_in", "instagram", {"payload": payload})
    msg = (
        payload.get("message")
        or payload.get("text")
        or payload.get("body")
        or ""
    )
    if not msg:
        return {"ok": True, "skipped": "no message"}
    decision = await agent.handle_customer_message(
        channel="instagram",
        customer_name=payload.get("fromName") or payload.get("from") or "Friend",
        customer_handle=payload.get("from") or payload.get("fromHandle") or "ig_user",
        text=msg,
        thread_id=payload.get("threadId"),
    )
    # If the agent decided this was a faq/smalltalk and no approval needed, reply on IG immediately.
    if decision.get("intent") in ("faq", "smalltalk") and not decision.get("needs_owner_approval"):
        thread_id = payload.get("threadId")
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
    msg = payload.get("message") or payload.get("text") or payload.get("body") or ""
    if not msg:
        return {"ok": True, "skipped": "no message"}
    decision = await agent.handle_customer_message(
        channel="whatsapp",
        customer_name=payload.get("fromName") or "Friend",
        customer_handle=payload.get("from") or "wa_user",
        text=msg,
        phone=payload.get("from"),
    )
    if decision.get("intent") in ("faq", "smalltalk") and not decision.get("needs_owner_approval"):
        phone = payload.get("from")
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
