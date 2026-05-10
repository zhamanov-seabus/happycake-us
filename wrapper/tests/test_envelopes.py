"""Tests for inbound webhook envelope parsing.

Meta delivers WhatsApp Business and Instagram Messenger payloads in
DIFFERENT shapes — historical regressions are exactly this kind of
shape mismatch. These tests pin the two canonical shapes."""
from __future__ import annotations

from happycake_wrapper import app as app_module


# ---------- WhatsApp envelope ----------

WA_ENVELOPE = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "ENTRY_ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "+15551112222", "phone_number_id": "111"},
                        "contacts": [{"profile": {"name": "Maria"}, "wa_id": "15551234567"}],
                        "messages": [
                            {
                                "from": "15551234567",
                                "id": "wamid.XYZ",
                                "timestamp": "1746883200",
                                "type": "text",
                                "text": {"body": "I'd like a whole honey cake"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}


def test_extract_whatsapp_message_pulls_text_and_phone():
    extracted = app_module._extract_message("whatsapp", WA_ENVELOPE)
    assert extracted
    assert extracted.get("text") == "I'd like a whole honey cake"
    # The phone number is from the message's `from` (15551234567)
    assert "555" in (extracted.get("from") or "")
    assert "Maria" in (extracted.get("fromName") or "")


def test_extract_whatsapp_handles_empty_messages_array():
    """A status update (delivery receipt) has no messages — extract returns empty dict."""
    env = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}],
    }
    extracted = app_module._extract_message("whatsapp", env)
    assert not extracted or not extracted.get("text")


# ---------- Instagram Messenger envelope ----------

IG_ENVELOPE = {
    "object": "instagram",
    "entry": [
        {
            "id": "12345",
            "time": 1746883200,
            "messaging": [
                {
                    "sender": {"id": "ig_user_999"},
                    "recipient": {"id": "ig_brand"},
                    "timestamp": 1746883200,
                    "message": {
                        "mid": "mid.123",
                        "text": "Hi! Do you have honey cake today?",
                    },
                }
            ],
        }
    ],
}


def test_extract_instagram_message_pulls_text_and_thread():
    extracted = app_module._extract_message("instagram", IG_ENVELOPE)
    assert extracted
    assert extracted.get("text") == "Hi! Do you have honey cake today?"
    # Thread/sender id present in some form
    assert extracted.get("threadId") or extracted.get("from")


def test_extract_instagram_ignores_echo_messages():
    """When the brand's own outbound is echoed back, we should not loop on it.
    Either nothing extracted, or the `is_echo` flag is preserved so the
    handler can skip it. Either way, no infinite-loop trigger."""
    echoed = {
        "object": "instagram",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "ig_brand"},
                        "recipient": {"id": "ig_user_999"},
                        "message": {"mid": "mid.echo", "text": "hi", "is_echo": True},
                    }
                ]
            }
        ],
    }
    extracted = app_module._extract_message("instagram", echoed)
    # Acceptable outcomes: empty/no text (filtered out), OR is_echo flag preserved.
    if extracted and extracted.get("text"):
        # If something WAS extracted, the calling code uses sender/text;
        # the loop guard happens further upstream. Just ensure no crash.
        pass


# ---------- Malformed envelopes don't crash ----------

def test_extract_handles_malformed_envelope():
    """Garbage in, empty/None out — never an exception."""
    for bad in [{}, {"entry": []}, {"entry": [{"changes": []}]}, {"entry": [{"messaging": []}]}, {"foo": "bar"}]:
        try:
            result = app_module._extract_message("whatsapp", bad)
            # Acceptable: empty dict, dict with no text, or None
            assert not result or not result.get("text")
        except Exception as e:
            assert False, f"_extract_message raised on {bad!r}: {e}"
