"""Tests for the customer memory layer.

Key derivation, exact-key recall, semantic recall (when fastembed is
available), and graceful degradation when it isn't."""
from __future__ import annotations
import json

import pytest

from happycake_wrapper import memory


# ---------- _key derivation ----------

def test_key_prefers_phone_for_whatsapp():
    k = memory._key(channel="whatsapp", handle=None, phone="+15551234567", customer_name="Maria")
    assert k == "whatsapp:+15551234567"


def test_key_prefers_handle_for_instagram():
    k = memory._key(channel="instagram", handle="ig_thread_abc", phone=None, customer_name="Maria")
    assert k == "instagram:ig_thread_abc"


def test_key_uses_visitor_id_for_website_not_placeholder_name():
    """The website route passes 'Site visitor' as customer_name; it should
    NOT collide every anonymous visitor onto one key."""
    k = memory._key(channel="website", handle="web-abc123", phone=None, customer_name="Site visitor")
    assert k == "website:web-abc123"


def test_key_falls_through_to_real_name_when_no_durable_id():
    """If nothing else, use a slug of a real name (NOT a placeholder)."""
    k = memory._key(channel="website", handle=None, phone=None, customer_name="Maria Ivanova")
    assert k == "website:name:maria-ivanova"


def test_key_returns_none_when_only_placeholder_name():
    """No durable id + only a placeholder name → no key (memory should skip)."""
    k = memory._key(channel="website", handle=None, phone=None, customer_name="Site visitor")
    assert k is None


# ---------- record_order + recall round-trip ----------

def test_record_then_recall_round_trip(tmp_path, monkeypatch):
    """An order recorded should be retrievable with the same identifier."""
    mem_path = tmp_path / "customer_memory.jsonl"
    monkeypatch.setattr(memory, "MEMORY_PATH", mem_path)

    memory.record_order(
        channel="whatsapp",
        customer_name="Maria",
        handle=None,
        phone="+15551234567",
        items_label='1× cake "Honey" — whole — $55.00',
        pickup_time="2026-05-10T16:00:00-05:00",
        notes=None,
        order_id="hc_test_001",
        items=[{"variation_id": "sq_var_whole_honey_cake", "quantity": 1}],
    )
    rec = memory.recall(channel="whatsapp", phone="+15551234567")
    assert rec is not None
    assert rec["order_count"] == 1
    assert rec["customer_name"] == "Maria"
    assert "sq_var_whole_honey_cake" in rec["preferred_items"]


def test_recall_returns_none_for_first_time_customer(tmp_path, monkeypatch):
    mem_path = tmp_path / "customer_memory.jsonl"
    monkeypatch.setattr(memory, "MEMORY_PATH", mem_path)
    rec = memory.recall(channel="whatsapp", phone="+15559999999")
    assert rec is None


def test_recall_aggregates_multiple_orders_and_finds_preferred(tmp_path, monkeypatch):
    mem_path = tmp_path / "customer_memory.jsonl"
    monkeypatch.setattr(memory, "MEMORY_PATH", mem_path)

    for i in range(3):
        memory.record_order(
            channel="instagram",
            customer_name="Maria",
            handle="ig_thread_xyz",
            phone=None,
            items_label='1× cake "Honey" — whole',
            pickup_time=None,
            notes=None,
            order_id=f"hc_{i:03d}",
            items=[{"variation_id": "sq_var_whole_honey_cake", "quantity": 1}],
        )
    # one order of pistachio, to confirm the most-frequent wins
    memory.record_order(
        channel="instagram",
        customer_name="Maria",
        handle="ig_thread_xyz",
        phone=None,
        items_label='1× pistachio roll',
        pickup_time=None,
        notes=None,
        order_id="hc_pistachio",
        items=[{"variation_id": "sq_var_pistachio_roll", "quantity": 1}],
    )

    rec = memory.recall(channel="instagram", handle="ig_thread_xyz")
    assert rec["order_count"] == 4
    # whole honey cake appeared 3x, pistachio 1x → whole honey ranks first
    assert rec["preferred_items"][0] == "sq_var_whole_honey_cake"


# ---------- summary_for_prompt ----------

def test_summary_empty_for_first_time_customer():
    assert memory.summary_for_prompt(None) == ""
    assert memory.summary_for_prompt({"order_count": 0}) == ""


def test_summary_renders_returning_customer_block():
    rec = {
        "order_count": 2,
        "customer_name": "Maria",
        "last_order": {"items_label": "whole honey cake", "pickup_time": "2026-05-10T16:00:00-05:00"},
        "preferred_items": ["sq_var_whole_honey_cake"],
        "notes": [],
    }
    block = memory.summary_for_prompt(rec)
    assert "Maria" in block
    assert "Returning customer" in block
    assert "whole honey cake" in block


# ---------- semantic recall — only when fastembed is loadable ----------

def _embeddings_available() -> bool:
    """Skip semantic-search tests if the model isn't ready in this env."""
    try:
        from happycake_wrapper import embeddings
        return embeddings.warm()
    except Exception:
        return False


@pytest.mark.skipif(not _embeddings_available(), reason="fastembed not available in this environment")
def test_semantic_recall_finds_related_order(tmp_path, monkeypatch):
    mem_path = tmp_path / "customer_memory.jsonl"
    monkeypatch.setattr(memory, "MEMORY_PATH", mem_path)

    memory.record_order(
        channel="whatsapp",
        customer_name="Maria",
        handle=None,
        phone="+15551111111",
        items_label='1× cake "Honey" — whole — $55.00',
        pickup_time="2026-05-10T16:00:00-05:00",
        notes=None,
        order_id="hc_sem_001",
        items=[{"variation_id": "sq_var_whole_honey_cake", "quantity": 1}],
    )

    # Descriptive paraphrase — should match
    hits = memory.recall_semantic(query="a whole honey cake again", top_k=2, min_similarity=0.3)
    assert len(hits) >= 1
    assert "Honey" in hits[0]["items_label"]
    assert "_similarity" in hits[0]
    assert 0 < hits[0]["_similarity"] <= 1


@pytest.mark.skipif(not _embeddings_available(), reason="fastembed not available in this environment")
def test_semantic_recall_returns_empty_below_threshold(tmp_path, monkeypatch):
    mem_path = tmp_path / "customer_memory.jsonl"
    monkeypatch.setattr(memory, "MEMORY_PATH", mem_path)

    memory.record_order(
        channel="whatsapp", customer_name="Maria", handle=None, phone="+15551111111",
        items_label='1× cake "Honey" — whole', pickup_time=None, notes=None,
        order_id="hc_sem_002",
        items=[{"variation_id": "sq_var_whole_honey_cake", "quantity": 1}],
    )

    # Totally unrelated query — should not match
    hits = memory.recall_semantic(query="weather forecast for Tokyo", top_k=2, min_similarity=0.5)
    assert hits == []
