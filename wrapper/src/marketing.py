"""Marketing creative pipeline.

Flow:
  1. /marketing/draft (theme, audience, channel='instagram') →
       claude -p with brandbook → caption + suggested image →
       instagram_schedule_post → owner Telegram card (post:approve:<id> | post:reject:<id>) →
  2. Owner taps Approve → instagram_approve_post → instagram_publish_post →
       evidence/log.jsonl gets a marketing_publish entry.

Reuses owner_bot's inline-keyboard pattern. Adds a new callback prefix `post:`.
"""
from __future__ import annotations
import json
import logging
import secrets
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import claude_runner, evidence, mcp_client, owner_bot
from .config import PUBLIC_SITE_URL

log = logging.getLogger("happycake.marketing")

# pending[scheduled_post_id] = full draft dict, used when owner taps the button
_pending_posts: dict[str, dict[str, Any]] = {}

SOCIAL_IMAGES = [
    f"{PUBLIC_SITE_URL}/images/happy-cake-social-01.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-social-02.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-social-03.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-social-04.webp",
]
HERO_IMAGES = [
    f"{PUBLIC_SITE_URL}/images/happy-cake-hero-01.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-hero-02.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-hero-03.webp",
    f"{PUBLIC_SITE_URL}/images/happy-cake-hero-04.webp",
]


def _draft_prompt(theme: str, audience: str, channel: str) -> str:
    return f"""You are HappyCake's marketing-content drafter.

Channel: **{channel}**
Audience hint: {audience or 'Sugar Land regulars'}
Theme/angle: {theme}

Write ONE post draft following HappyCake brand rules (loaded in your system prompt). Output ONLY a JSON object — no fence, no prose:

{{
  "caption": "<the post caption, brand voice, 600-1000 chars including the closing>",
  "image_role": "social" | "hero",
  "image_index": 0..3,
  "rationale": "1-line why this caption + image fit the theme"
}}

Hard rules for the caption:
- Wordmark HappyCake (one word, two capitals).
- Cake names quoted: cake "Honey", cake "Pistachio Roll".
- Specific quantities; no hyperbole. 0–3 emojis max, never in price/menu lines.
- End with: "Order on the site at happycake.us or send a message on WhatsApp."
- 600–1000 chars.
"""


def draft_post(theme: str, audience: str = "", channel: str = "instagram") -> dict[str, Any]:
    """Run claude -p to draft a post. Returns parsed JSON or a fallback."""
    raw = claude_runner.run_claude(_draft_prompt(theme, audience, channel), channel=channel)
    body = raw.strip()
    # Reuse the runner's fence stripper
    body = claude_runner._strip_fence(body)  # noqa: SLF001
    try:
        d = json.loads(body)
        d.setdefault("caption", "Today's bake is on the counter. Order on the site at happycake.us or send a message on WhatsApp.")
        d.setdefault("image_role", "social")
        d.setdefault("image_index", 0)
        d.setdefault("rationale", "")
        return d
    except json.JSONDecodeError:
        return {
            "caption": body[:2000] or "Today's bake is on the counter. Order on the site at happycake.us or send a message on WhatsApp.",
            "image_role": "social",
            "image_index": 0,
            "rationale": "fallback (json parse failed)",
        }


def _resolve_image(role: str, idx: int) -> str:
    pool = HERO_IMAGES if role == "hero" else SOCIAL_IMAGES
    return pool[max(0, min(idx, len(pool) - 1))]


async def queue_for_owner_approval(theme: str, audience: str = "") -> dict[str, Any]:
    """Draft → instagram_schedule_post → owner Telegram card. Returns the
    pending entry so the caller can also see the scheduledPostId."""
    draft = draft_post(theme=theme, audience=audience)
    image_url = _resolve_image(draft.get("image_role", "social"), draft.get("image_index", 0))

    # Schedule in sandbox (NEVER published — instagram_publish_post is gated on owner Approve)
    scheduled = mcp_client.call("instagram_schedule_post", {
        "imageUrl": image_url,
        "caption": draft["caption"],
    })
    scheduled_id = (scheduled or {}).get("scheduledPostId") or (scheduled or {}).get("id")
    if not scheduled_id:
        evidence.log("error", "system", {"where": "marketing_schedule", "resp": str(scheduled)[:300]})
        scheduled_id = f"draft_{secrets.token_hex(4)}"

    _pending_posts[scheduled_id] = {
        "scheduled_id": scheduled_id,
        "image_url": image_url,
        "caption": draft["caption"],
        "theme": theme,
        "audience": audience,
        "rationale": draft.get("rationale", ""),
    }
    evidence.log("marketing_draft", "system", {
        "scheduled_id": scheduled_id,
        "theme": theme,
        "image_url": image_url,
        "caption_preview": draft["caption"][:140],
    })

    # Owner card
    if owner_bot.TELEGRAM_OWNER_CHAT_ID:
        try:
            text = (
                f"🎂 <b>Post draft ready for review</b>\n\n"
                f"<b>Theme:</b> {theme}\n"
                f"<b>Audience:</b> {audience or '(default)'}\n\n"
                f"<i>{draft['caption']}</i>\n\n"
                f"Scheduled id: <code>{scheduled_id}</code>"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve & publish", callback_data=f"post:approve:{scheduled_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"post:reject:{scheduled_id}"),
            ]])
            app = owner_bot.get_app()
            await app.bot.send_photo(
                chat_id=owner_bot.TELEGRAM_OWNER_CHAT_ID,
                photo=image_url,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            log.exception("owner card for post draft failed: %s", e)
            evidence.log("error", "system", {"where": "marketing_owner_card", "error": str(e)})

    return {
        "scheduled_id": scheduled_id,
        "image_url": image_url,
        "caption": draft["caption"],
        "rationale": draft.get("rationale", ""),
    }


async def on_owner_post_decision(scheduled_id: str, verb: str) -> None:
    """Called by owner_bot when ✅/❌ is tapped on a post draft."""
    pending = _pending_posts.pop(scheduled_id, None)
    evidence.log("marketing_decision", "system", {
        "scheduled_id": scheduled_id,
        "decision": verb,
        "had_pending": pending is not None,
    })
    if verb != "approve":
        return
    try:
        mcp_client.call("instagram_approve_post", {"scheduledPostId": scheduled_id})
        mcp_client.call("instagram_publish_post", {"scheduledPostId": scheduled_id})
        evidence.log("marketing_publish", "system", {"scheduled_id": scheduled_id})
    except Exception as e:
        evidence.log("error", "system", {"where": "marketing_publish", "error": str(e)})
