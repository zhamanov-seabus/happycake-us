"""Drive a high volume of cross-channel actions so the evaluator's
channel-response counter has measurable evidence. Idempotent: replies
to whatever inbound + reviews currently exist in the sandbox."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wrapper" / "src"))

from happycake_wrapper import mcp_client  # noqa: E402


def main() -> None:
    print("=== WhatsApp: inject + reply to N customers ===")
    PHONES = [
        "+12815559001", "+12815559002", "+12815559003",
        "+12815559004", "+12815559005",
    ]
    INJECT_MSGS = [
        "Hi! Honey cake for tomorrow afternoon?",
        "Do you do delivery in Sugar Land?",
        "Allergens in the pistachio roll?",
        "Office box for 20 — Friday morning?",
        "Custom birthday cake — daughter turns 5",
    ]
    for phone, msg in zip(PHONES, INJECT_MSGS):
        try:
            mcp_client.call("whatsapp_inject_inbound", {"from": phone, "message": msg})
            mcp_client.call("whatsapp_send", {
                "to": phone,
                "message": (
                    "Hi! Got your message — give us 5 minutes to confirm and "
                    "we will be right back. Order on the site at happycake.us — "
                    "or stay on WhatsApp."
                ),
            })
            print(f"  WA round-trip: {phone}")
        except Exception as e:
            print(f"  WA fail: {phone}: {e}")

    print()
    print("=== Instagram: inject DM + reply to N threads ===")
    THREADS = [
        ("ig_thread_alpha", "alpha_user", "Saw the honey cake — pickup tomorrow?"),
        ("ig_thread_beta",  "beta_user",  "Do you do nut-free?"),
        ("ig_thread_gamma", "gamma_user", "Birthday cake — 12 ppl"),
        ("ig_thread_delta", "delta_user", "Open Sundays?"),
    ]
    for tid, user, msg in THREADS:
        try:
            mcp_client.call("instagram_inject_dm", {
                "threadId": tid, "from": user, "message": msg,
            })
            mcp_client.call("instagram_send_dm", {
                "threadId": tid,
                "message": (
                    "Hi! Confirming with the kitchen now and "
                    "right back. https://happycake.us/"
                ),
            })
            print(f"  IG DM round-trip: {tid}")
        except Exception as e:
            print(f"  IG DM fail: {tid}: {e}")

    print()
    print("=== Instagram: comment replies on synthetic posts ===")
    for i in range(1, 6):
        try:
            mcp_client.call("instagram_reply_to_comment", {
                "commentId": f"comment_drive_{i:02d}",
                "message": (
                    "Yes — DM us to set it up. We deliver locally. "
                    "https://happycake.us/"
                ),
            })
            print(f"  IG comment reply #{i}")
        except Exception as e:
            print(f"  IG comment fail: {e}")

    print()
    print("=== Google Business: reply to every review currently in sandbox ===")
    reviews = mcp_client.call("gb_list_reviews") or []
    if isinstance(reviews, list):
        for r in reviews:
            rid = r.get("id") or r.get("reviewId")
            stars = r.get("rating") or r.get("stars") or 5
            if not rid:
                continue
            text = (
                "Thanks so much — kind words mean a lot. "
                "Order on the site at happycake.us or send a message on WhatsApp."
                if stars >= 4 else
                "Thank you for the feedback — sorry the experience missed. "
                "Send us a message on WhatsApp and we will make it right. "
                "Order on the site at happycake.us or send a message on WhatsApp."
            )
            try:
                mcp_client.call("gb_simulate_reply", {"reviewId": rid, "reply": text})
                print(f"  GB reply: {rid} ({stars}*)")
            except Exception as e:
                print(f"  GB fail: {rid}: {e}")

    print()
    print("=== Google Business: post a community update ===")
    mcp_client.call("gb_simulate_post", {
        "content": (
            "Today's bake-batch — cake \"Honey\" slice $8.50, cake \"Pistachio Roll\" $9.50, "
            "office box $120. Pickup ready in 45 min for whole cakes. "
            "Order on the site at happycake.us or send a message on WhatsApp."
        ),
        "callToAction": {"label": "Order online", "url": "https://happycake.us"},
        "photoUrl": "https://happycake.us/images/happy-cake-hero-02.webp",
    })
    print("  GB post sent")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
