"""Stock-aware ordering layer.

Two regimes the wrapper applies on owner Approve:

1. Same-day pickup → consult sandbox `square_get_inventory` for the ordered
   variations; if anything is sold out we reject the order before creating
   the POS order, and tell the customer.

2. Future-day pickup → decompose items into ingredients via data/recipes.yml,
   decrement data/ingredients.yml, and surface a Telegram shopping list to
   the owner if any ingredient drops below its reorder threshold.

This module is intentionally pure — no Telegram calls, no FastAPI awareness.
The wrapper layers (agent.py, owner_bot.py) call the helpers below.
"""
from __future__ import annotations
import math
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .config import RECIPES_PATH, INGREDIENTS_PATH

# Sugar Land is in Central Time. Same-day decisions hinge on the bakery's
# local calendar day, not the wrapper's UTC day.
LOCAL_TZ = ZoneInfo("America/Chicago")


# ---------- typed shapes ----------

@dataclass
class Shortfall:
    """A single same-day shortfall: variation X requested Y, only Z available."""
    variation_id: str
    requested: int
    available: int


@dataclass
class ReorderAlert:
    """An ingredient crossed the reorder threshold during the last drawdown."""
    name: str
    on_hand: float
    reorder_at: float
    unit: str


@dataclass
class PurchaseItem:
    """One row on the owner's shopping list."""
    name: str
    qty: int                # number of packs to buy
    unit: str               # unit per pack (e.g. 'g', 'ml', 'each')
    pack_qty: float         # qty in each pack (e.g. 250 for a 250 g tub)
    on_hand: float
    reorder_at: float
    supplier_hint: str | None = None


@dataclass
class DrawdownResult:
    applied: bool
    needs: dict[str, dict[str, Any]] = field(default_factory=dict)
    before: dict[str, float] = field(default_factory=dict)
    after: dict[str, float] = field(default_factory=dict)
    shortfalls: list[Shortfall] = field(default_factory=list)  # ingredient shortfalls (we still apply, but flag)
    crossed: list[ReorderAlert] = field(default_factory=list)


# ---------- file IO (YAML round-trip) ----------

def load_recipes() -> dict[str, Any]:
    return yaml.safe_load(RECIPES_PATH.read_text(encoding="utf-8")).get("recipes", {})


def load_ingredients() -> dict[str, Any]:
    return yaml.safe_load(INGREDIENTS_PATH.read_text(encoding="utf-8")).get("ingredients", {})


def save_ingredients(state: dict[str, Any]) -> None:
    """Atomic rewrite — temp file in same dir, then rename."""
    payload = {"ingredients": state}
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(INGREDIENTS_PATH.parent),
        prefix=".ingredients-",
        suffix=".yml.tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
        os.replace(tmp_path, INGREDIENTS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------- date helpers ----------

def is_same_day(pickup_iso: str | None) -> bool:
    """True if pickup is on the same calendar day in Sugar Land local time.

    Treats missing/invalid pickup as 'same day' so the safer ready-stock check
    runs (better to confirm against the counter than silently draw ingredients).
    """
    if not pickup_iso:
        return True
    try:
        # Tolerate '2026-05-09T15:00:00', '2026-05-09T15:00:00-05:00', '2026-05-09'
        s = pickup_iso.strip()
        if "T" not in s:
            s += "T00:00:00"
        # If no timezone, assume local
        if not (s.endswith("Z") or "+" in s[10:] or s.count("-") > 2):
            dt = datetime.fromisoformat(s).replace(tzinfo=LOCAL_TZ)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return True
    now_local = datetime.now(LOCAL_TZ)
    pickup_local = dt.astimezone(LOCAL_TZ)
    return pickup_local.date() == now_local.date()


# ---------- ready-stock (sandbox) ----------

def check_ready_stock(items: list[dict[str, Any]]) -> list[Shortfall]:
    """Call sandbox square_get_inventory for the requested variations.
    Returns Shortfalls — empty list means everything available."""
    if not items:
        return []
    # Local import so this module is safe to import in unit tests
    from . import mcp_client

    variation_ids = list({it.get("variation_id") for it in items if it.get("variation_id")})
    if not variation_ids:
        return []

    try:
        resp = mcp_client.call("square_get_inventory", {"variationIds": variation_ids}) or {}
    except Exception:
        # If the inventory check itself fails, treat as 'unknown' — best to
        # let the owner decide rather than silently approve.
        return [Shortfall(variation_id=v, requested=1, available=-1) for v in variation_ids]

    inv_list = resp.get("inventory", []) if isinstance(resp, dict) else []
    by_id = {row.get("variationId"): row for row in inv_list}
    shortfalls: list[Shortfall] = []
    # Aggregate requested per variation_id (in case the agent listed the same id twice)
    requested_by_var: dict[str, int] = {}
    for it in items:
        v = it.get("variation_id")
        if not v:
            continue
        requested_by_var[v] = requested_by_var.get(v, 0) + int(it.get("quantity", 1))
    for v, req in requested_by_var.items():
        row = by_id.get(v) or {}
        in_stock = bool(row.get("inStock", row.get("in_stock", True)))
        avail = int(row.get("quantity", 999) if in_stock else 0)
        if not in_stock or avail < req:
            shortfalls.append(Shortfall(variation_id=v, requested=req, available=avail))
    return shortfalls


# ---------- recipe expansion ----------

def compute_ingredient_needs(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sum the BOM across all order items.

    Returns: { ingredient_name: { qty, unit } }
    Ignores items whose variation_id has no recipe (with a quiet pass).
    """
    recipes = load_recipes()
    needs: dict[str, dict[str, Any]] = {}
    for it in items:
        v = it.get("variation_id")
        qty = float(it.get("quantity", 1))
        recipe = recipes.get(v)
        if not recipe:
            continue
        per_unit_yield = float(recipe.get("yields", 1) or 1)
        scale = qty / per_unit_yield
        for ing, spec in (recipe.get("ingredients") or {}).items():
            ing_qty = float(spec.get("qty", 0)) * scale
            unit = spec.get("unit", "g")
            if ing not in needs:
                needs[ing] = {"qty": 0.0, "unit": unit}
            elif needs[ing]["unit"] != unit:
                # Ingredient appears in two recipes with conflicting units —
                # leave the first; downstream will surface the mismatch.
                continue
            needs[ing]["qty"] += ing_qty
    # Round to a sensible precision for the YAML round-trip.
    for ing in needs:
        needs[ing]["qty"] = round(needs[ing]["qty"], 2)
    return needs


# ---------- ingredient drawdown ----------

def decrement_ingredients(needs: dict[str, dict[str, Any]]) -> DrawdownResult:
    """Apply needs to ingredients.yml. Even if some ingredients can't fully
    cover the order we still decrement (allowing on_hand to go negative is
    explicit signal that the kitchen has a deficit) — but we surface that
    via DrawdownResult.shortfalls so the wrapper can warn the owner."""
    state = load_ingredients()
    before = {k: float(state[k].get("on_hand", 0)) for k in state}
    after = dict(before)
    shortfalls: list[Shortfall] = []
    crossed: list[ReorderAlert] = []

    for ing, spec in needs.items():
        if ing not in state:
            # Recipe references an ingredient that's not in our pantry — flag it.
            shortfalls.append(Shortfall(variation_id=ing, requested=int(spec["qty"]), available=0))
            continue
        on_hand_before = float(state[ing].get("on_hand", 0))
        new_on_hand = on_hand_before - float(spec["qty"])
        state[ing]["on_hand"] = round(new_on_hand, 2)
        after[ing] = state[ing]["on_hand"]
        reorder_at = float(state[ing].get("reorder_at", 0))
        if on_hand_before >= reorder_at and new_on_hand < reorder_at:
            crossed.append(ReorderAlert(
                name=ing,
                on_hand=new_on_hand,
                reorder_at=reorder_at,
                unit=str(state[ing].get("unit", "g")),
            ))
        if new_on_hand < 0:
            shortfalls.append(Shortfall(
                variation_id=ing,
                requested=int(spec["qty"]),
                available=int(on_hand_before),
            ))

    save_ingredients(state)
    return DrawdownResult(
        applied=True,
        needs={k: dict(v) for k, v in needs.items()},
        before=before,
        after=after,
        shortfalls=shortfalls,
        crossed=crossed,
    )


# ---------- purchase list ----------

def compute_purchase_list(state: dict[str, Any] | None = None) -> list[PurchaseItem]:
    """Anything currently below reorder_at, with qty rounded up to the next
    whole pack size. Idempotent — safe to call any time."""
    if state is None:
        state = load_ingredients()
    items: list[PurchaseItem] = []
    for name, spec in state.items():
        on_hand = float(spec.get("on_hand", 0))
        reorder_at = float(spec.get("reorder_at", 0))
        if on_hand >= reorder_at:
            continue
        deficit = max(0.0, reorder_at - on_hand)
        # We want enough to comfortably restock — buy at least 2× the deficit
        # rounded up to whole packs, so the next big order doesn't immediately
        # trip the alert again.
        target = max(deficit * 2, reorder_at)
        pack = spec.get("pack_size") or {}
        pack_qty = float(pack.get("qty", 1) or 1)
        packs_needed = int(math.ceil(target / pack_qty))
        items.append(PurchaseItem(
            name=name,
            qty=packs_needed,
            unit=str(pack.get("unit", spec.get("unit", "g"))),
            pack_qty=pack_qty,
            on_hand=on_hand,
            reorder_at=reorder_at,
            supplier_hint=spec.get("supplier_hint"),
        ))
    # Sort: most-deficit first
    items.sort(key=lambda p: (p.on_hand - p.reorder_at))
    return items


# ---------- /restock command logic ----------

def restock(name: str, qty: float) -> dict[str, Any]:
    """Add qty to ingredient `name` (in its native unit). Returns new on_hand."""
    state = load_ingredients()
    if name not in state:
        return {"ok": False, "error": f"unknown ingredient '{name}'", "available": list(state.keys())}
    if qty <= 0:
        return {"ok": False, "error": "qty must be positive"}
    state[name]["on_hand"] = round(float(state[name].get("on_hand", 0)) + float(qty), 2)
    save_ingredients(state)
    return {"ok": True, "on_hand": state[name]["on_hand"], "unit": state[name].get("unit")}


# ---------- agent-prompt summary ----------

def stock_summary_for_prompt(max_lines: int = 20) -> str:
    """Compact human-readable stock summary the agent reads at chat time.
    Falls back gracefully if the sandbox is unreachable."""
    from . import mcp_client

    catalog_summary = ""
    try:
        cat_resp = mcp_client.call("square_list_catalog", {"limit": 50}) or {}
        catalog_items = cat_resp.get("catalog", []) if isinstance(cat_resp, dict) else []
        var_ids = [c.get("variationId") for c in catalog_items if c.get("variationId")]
        inv_resp = mcp_client.call("square_get_inventory", {"variationIds": var_ids}) or {}
        inv_rows = inv_resp.get("inventory", []) if isinstance(inv_resp, dict) else []
        by_var = {r.get("variationId"): r for r in inv_rows}
        lines = []
        for c in catalog_items[:max_lines]:
            v = c.get("variationId")
            row = by_var.get(v) or {}
            in_stock = row.get("inStock", row.get("in_stock", True))
            qty = row.get("quantity")
            qty_label = f"{qty} on the counter" if qty is not None and in_stock else ("in stock" if in_stock else "sold out today")
            lines.append(f"- {c.get('name')} (`{v}`): {qty_label}")
        catalog_summary = "\n".join(lines) if lines else "(could not read sandbox inventory)"
    except Exception:
        catalog_summary = "(sandbox unreachable — answer same-day questions cautiously)"

    # Ingredient health: anything below reorder_at flagged.
    try:
        ings = load_ingredients()
        flagged = [
            f"- {n} ({s.get('on_hand')} {s.get('unit')}, threshold {s.get('reorder_at')})"
            for n, s in ings.items()
            if float(s.get('on_hand', 0)) < float(s.get('reorder_at', 0))
        ]
        ing_summary = "All ingredients above reorder thresholds." if not flagged else "Below threshold:\n" + "\n".join(flagged)
    except Exception:
        ing_summary = "(could not read ingredient state)"

    return (
        "## Today's stock (live)\n\n"
        "Ready on the counter / in the case:\n"
        f"{catalog_summary}\n\n"
        "Kitchen ingredients:\n"
        f"{ing_summary}\n\n"
        "Rules:\n"
        "- For SAME-DAY pickups, only promise items that are currently in stock above. "
        "If something is sold out, decline politely and suggest the closest in-stock alternative.\n"
        "- For FUTURE-DAY pickups, the kitchen will bake fresh — confirm with the lead time. "
        "The wrapper checks ingredient feasibility automatically when the owner approves; "
        "you don't need to enumerate ingredients to the customer.\n"
    )


def to_jsonable(obj: Any) -> Any:
    """Helper for evidence.log payloads — turns dataclasses into dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj
