"""Tests for the stock-aware ordering layer.

Same-day stock check, future-day ingredient drawdown, reorder threshold,
purchase-list pack rounding. The hot paths the agent depends on for
honest-inventory promises."""
from __future__ import annotations
from unittest.mock import patch

import pytest

from happycake_wrapper import inventory


# ---------- is_same_day ----------

def test_is_same_day_returns_true_for_today_local():
    """A pickup_iso for the current Sugar Land day is same-day."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today_local = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%dT15:00:00-05:00")
    assert inventory.is_same_day(today_local) is True


def test_is_same_day_handles_tomorrow():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Chicago")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00-05:00")
    assert inventory.is_same_day(tomorrow) is False


def test_is_same_day_none_treated_as_today():
    """No pickup time = customer wants it now = same-day path."""
    assert inventory.is_same_day(None) is True


# ---------- compute_ingredient_needs ----------

def test_ingredient_needs_aggregates_across_items():
    """A whole honey cake + a pistachio roll should sum the shared ingredients."""
    items = [
        {"variation_id": "sq_var_whole_honey_cake", "quantity": 1},
        {"variation_id": "sq_var_pistachio_roll", "quantity": 2},
    ]
    needs = inventory.compute_ingredient_needs(items)
    # Whole honey cake uses flour 320g; pistachio roll uses flour 45g × 2 = 90g
    assert needs.get("flour", {}).get("qty") == pytest.approx(320 + 45 * 2)
    # Pistachio paste only used by pistachio roll: 40g × 2
    assert needs.get("pistachio_paste", {}).get("qty") == pytest.approx(80)


def test_ingredient_needs_empty_for_unknown_variation():
    """Unknown variation_id returns no needs (and doesn't crash)."""
    needs = inventory.compute_ingredient_needs([{"variation_id": "sq_var_does_not_exist", "quantity": 1}])
    assert needs == {}


# ---------- decrement_ingredients + reorder threshold ----------

def test_drawdown_crosses_reorder_threshold(tmp_path, monkeypatch):
    """When on_hand drops below reorder_at, the result.crossed list names it."""
    # Build a temp ingredients file with one ingredient near threshold.
    ing_path = tmp_path / "ingredients.yml"
    ing_path.write_text(
        "ingredients:\n"
        "  butter: { on_hand: 250, unit: g, reorder_at: 200, pack_size: { qty: 250, unit: g } }\n"
    )
    monkeypatch.setattr(inventory, "INGREDIENTS_PATH", ing_path)

    needs = {"butter": {"qty": 100, "unit": "g"}}
    res = inventory.decrement_ingredients(needs)
    assert res.applied is True
    # 250 - 100 = 150, below 200 → crossed
    assert any(c.name == "butter" for c in res.crossed)
    assert res.after["butter"] == pytest.approx(150)


def test_drawdown_no_cross_when_well_above_threshold(tmp_path, monkeypatch):
    """If we don't cross the threshold, crossed is empty."""
    ing_path = tmp_path / "ingredients.yml"
    ing_path.write_text(
        "ingredients:\n"
        "  flour: { on_hand: 4500, unit: g, reorder_at: 1500, pack_size: { qty: 1000, unit: g } }\n"
    )
    monkeypatch.setattr(inventory, "INGREDIENTS_PATH", ing_path)

    res = inventory.decrement_ingredients({"flour": {"qty": 500, "unit": "g"}})
    assert res.applied is True
    assert res.crossed == []


def test_drawdown_shortfalls_when_request_exceeds_stock(tmp_path, monkeypatch):
    """If we don't have enough, result.shortfalls flags it. The current
    implementation still applies the drawdown (allowing on_hand to go
    negative) so the kitchen knows the deficit; what matters is that
    the shortfall is reported so the customer-facing path can react."""
    ing_path = tmp_path / "ingredients.yml"
    ing_path.write_text(
        "ingredients:\n"
        "  vanilla: { on_hand: 5, unit: ml, reorder_at: 30, pack_size: { qty: 100, unit: ml } }\n"
    )
    monkeypatch.setattr(inventory, "INGREDIENTS_PATH", ing_path)

    res = inventory.decrement_ingredients({"vanilla": {"qty": 50, "unit": "ml"}})
    assert any(s.variation_id == "vanilla" for s in res.shortfalls)


# ---------- compute_purchase_list ----------

def test_purchase_list_rounds_up_to_pack_size(tmp_path, monkeypatch):
    """A 250g shortfall on a 1kg-pack ingredient should buy 1 pack, not 0."""
    ing_path = tmp_path / "ingredients.yml"
    ing_path.write_text(
        "ingredients:\n"
        "  honey: { on_hand: 100, unit: g, reorder_at: 400, pack_size: { qty: 1000, unit: g } }\n"
    )
    monkeypatch.setattr(inventory, "INGREDIENTS_PATH", ing_path)

    purchase = inventory.compute_purchase_list()
    # We're 300g below reorder_at (400 - 100 = 300), but the gap is to bring
    # us back to a healthy buffer. compute_purchase_list rounds UP to the
    # next pack regardless. Verify at least one pack of honey is suggested.
    by_name = {p.name: p for p in purchase}
    assert "honey" in by_name
    # PurchaseItem.qty is the number of packs to buy.
    assert by_name["honey"].qty >= 1
    assert by_name["honey"].pack_qty == 1000
