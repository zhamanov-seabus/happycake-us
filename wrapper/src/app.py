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

from . import agent, evidence, marketing, order_events, owner_bot
from .config import PUBLIC_TUNNEL_URL, TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("happycake.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the owner-decision + edit-message + post-approval callbacks before polling starts
    owner_bot.register_decision_handler(agent.on_owner_decision)
    owner_bot.register_edit_message_handler(agent.on_owner_edit_message)
    owner_bot.register_post_decision_handler(marketing.on_owner_post_decision)
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


# ---------- Marketing creative pipeline ----------

class DraftIn(BaseModel):
    theme: str
    audience: str | None = None


@app.post("/marketing/draft")
async def marketing_draft(payload: DraftIn) -> dict:
    """Generate a post draft, schedule it (un-published), and send the
    owner an approval card on Telegram. Owner taps Approve → published."""
    out = await marketing.queue_for_owner_approval(
        theme=payload.theme,
        audience=payload.audience or "",
    )
    return {"ok": True, **out}


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

def _extract_comment(payload: dict) -> dict:
    """Pull an Instagram comment event from a Meta-style envelope.

    Shape: entry[*].changes[*] where field == 'comments' and value carries
    {id, from:{id,username}, media:{id}, text}. Returns {} if not a comment.
    """
    try:
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") != "comments":
                    continue
                v = change.get("value") or {}
                text = v.get("text")
                if not text:
                    continue
                frm = v.get("from") or {}
                return {
                    "text": text,
                    "comment_id": v.get("id"),
                    "media_id": (v.get("media") or {}).get("id"),
                    "from_user_id": frm.get("id"),
                    "fromName": frm.get("username") or frm.get("id") or "ig_user",
                }
    except (TypeError, AttributeError):
        pass
    return {}


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

    # Meta WA envelope — entry[*].changes[*].value.messages[*]
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
                        "threadId": m.get("threadId") or value.get("threadId"),
                    }
    except (TypeError, AttributeError):
        pass

    # Meta Messenger envelope (Instagram + Messenger) —
    #   entry[*].messaging[*].{sender:{id}, message:{text}}
    try:
        for entry in payload.get("entry", []) or []:
            for ev in entry.get("messaging", []) or []:
                m = ev.get("message") or {}
                text = m.get("text")
                if not text:
                    continue
                sender_id = (ev.get("sender") or {}).get("id")
                # IG sandbox sometimes carries threadId here or on the sender
                thread_id = ev.get("threadId") or m.get("threadId") or sender_id
                return {
                    "text": text,
                    "from": sender_id,
                    "fromName": sender_id,
                    "threadId": thread_id,
                }
    except (TypeError, AttributeError):
        pass

    return {}


# ---------- Channel processing (async, fire-and-forget from webhooks) ----------

async def _process_inbound(channel: str, extracted: dict) -> None:
    """Run the agent + side effects for an extracted inbound message.
    Called as a background task from the webhook handlers so the webhook
    returns HTTP 202 within ms (sandbox forwarder has a short timeout)."""
    msg = extracted.get("text") or ""
    if not msg:
        return
    sender = extracted.get("from")
    decision = await agent.handle_customer_message(
        channel=channel,
        customer_name=extracted.get("fromName") or "Friend",
        customer_handle=sender or f"{channel}_user",
        text=msg,
        thread_id=extracted.get("threadId"),
        phone=sender if channel == "whatsapp" else None,
    )
    # Inline reply for benign FAQ/smalltalk
    if decision.get("intent") in ("faq", "smalltalk") and not decision.get("needs_owner_approval"):
        from . import mcp_client
        reply_text = decision.get("reply_text", "Thanks — back to you shortly.")
        try:
            if channel == "instagram":
                tid = extracted.get("threadId")
                if tid:
                    mcp_client.call("instagram_send_dm", {"threadId": tid, "message": reply_text})
                    evidence.log("customer_reply", "instagram", {"text": reply_text[:300]})
            elif channel == "whatsapp":
                if sender:
                    mcp_client.call("whatsapp_send", {"to": sender, "message": reply_text})
                    evidence.log("customer_reply", "whatsapp", {"text": reply_text[:300]})
        except Exception as e:
            evidence.log("error", "system", {"where": f"{channel}_inline_reply", "error": str(e)})


# ---------- Instagram webhook ----------

@app.post("/webhook/instagram")
async def webhook_instagram(payload: dict) -> dict:
    evidence.log("webhook_in", "instagram", {"payload": payload})
    # Comments and DMs both arrive on this endpoint. Comments need a different
    # reply tool (instagram_reply_to_comment), so split here.
    comment = _extract_comment(payload)
    if comment.get("text"):
        asyncio.create_task(_process_comment(comment))
        return {"ok": True, "accepted": True, "kind": "comment"}
    extracted = _extract_message("instagram", payload)
    if not extracted.get("text"):
        return {"ok": True, "skipped": "no message", "shape_seen": list(payload.keys())[:6]}
    asyncio.create_task(_process_inbound("instagram", extracted))
    return {"ok": True, "accepted": True, "kind": "dm"}


async def _process_comment(comment: dict) -> None:
    """Run the agent for an IG comment and reply via instagram_reply_to_comment.

    Comments are public; we don't gate them on owner approval (a public no-op
    silence looks worse than a public reply). Treats the comment text as the
    customer message; the agent decides intent. If order_intent, also fires
    an owner card so the team knows to nudge the commenter into a DM.
    """
    text = comment["text"]
    decision = await agent.handle_customer_message(
        channel="instagram",
        customer_name=comment.get("fromName") or "ig_user",
        customer_handle=comment.get("from_user_id") or "ig_user",
        text=text,
        thread_id=comment.get("comment_id"),  # carry comment id for reply
    )
    reply_text = decision.get("reply_text") or "Thanks — DM us and we'll set this up."
    cid = comment.get("comment_id")
    if cid:
        from . import mcp_client
        try:
            mcp_client.call("instagram_reply_to_comment", {
                "commentId": cid,
                "message": reply_text,
            })
            evidence.log("customer_reply", "instagram", {"kind": "comment_reply", "comment_id": cid, "text": reply_text[:300]})
        except Exception as e:
            evidence.log("error", "system", {"where": "ig_comment_reply", "error": str(e)})


# ---------- WhatsApp webhook ----------

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict) -> dict:
    evidence.log("webhook_in", "whatsapp", {"payload": payload})
    extracted = _extract_message("whatsapp", payload)
    if not extracted.get("text"):
        return {"ok": True, "skipped": "no message", "shape_seen": list(payload.keys())[:6]}
    asyncio.create_task(_process_inbound("whatsapp", extracted))
    return {"ok": True, "accepted": True}
