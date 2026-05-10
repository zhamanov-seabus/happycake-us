"""Franchise inquiry scoring. Pure function — given a validated inquiry
payload, returns 0–100 based on capital fit, timeline urgency, city tier,
and free-text quality.

The score drives Telegram routing: hot leads (≥75) get an immediate
🔥 card; warm (50–74) get the standard FYI; cool (<50) still log but
the owner notification is gentler. Lets a non-technical operator
prioritise without reading every form."""
from __future__ import annotations
from dataclasses import dataclass


# Texas metro tiers — operators in larger metros have more market depth
# and better access to qualified staff. This is the brandbook + sandbox
# sales-history view, not a snobbery ranking; smaller cities can still
# work with the right operator.
_TIER_1 = {"houston", "dallas", "austin", "san antonio", "fort worth"}
_TIER_2 = {"el paso", "lubbock", "amarillo", "plano", "irving",
           "frisco", "the woodlands", "katy", "pearland", "round rock", "corpus christi"}

# Capital ranges → fit score against the recommended unit ($250-400K).
_CAPITAL_FIT = {
    "250-400k": 100,
    "400-600k": 90,    # Room for a premium location, slight over-capitalisation
    "600k+":    85,    # Multi-unit appetite, but signals more sophisticated negotiator
    "raising":  40,    # Genuine intent unproven; still worth a conversation
}

# Timeline → urgency score. "Within 3 months" is the highest signal of
# real intent.
_TIMELINE_URGENCY = {
    "0-3mo":     100,
    "3-6mo":     80,
    "6-12mo":    55,
    "exploring": 25,
}


@dataclass
class FranchiseScore:
    total: int            # 0–100
    capital: int
    timeline: int
    city_tier: int
    text_quality: int
    label: str            # "hot" | "warm" | "cool"
    reasons: list[str]    # human-readable explanation

    def emoji(self) -> str:
        return {"hot": "🔥", "warm": "🤝", "cool": "📩"}.get(self.label, "📩")


def _score_city(city: str) -> tuple[int, str]:
    c = (city or "").strip().lower()
    if c in _TIER_1:
        return 100, f"Tier-1 metro ({city}) — deep market"
    if c in _TIER_2:
        return 75, f"Tier-2 metro ({city}) — solid market"
    if c:
        return 55, f"Outside-tier city ({city}) — operator-dependent"
    return 0, "City missing"


def _score_text(message: str) -> tuple[int, str]:
    """Free-text quality: length, presence of specifics (operator background,
    target neighbourhood, multi-unit intent). Cheap heuristic, not NLP — the
    point is to separate the one-line 'interested' replies from the 200-word
    operators-with-a-plan replies."""
    m = (message or "").strip()
    if not m:
        return 30, "No message — neutral, no signal"
    if len(m) < 40:
        return 35, "Brief message — light signal"
    score = 60
    reasons_bits: list[str] = []
    keywords = {
        "operating": "operating-experience signal",
        "restaurant": "restaurant-experience signal",
        "retail": "retail-experience signal",
        "multi": "multi-unit appetite",
        "neighborhood": "specific location thinking",
        "neighbourhood": "specific location thinking",
        "kitchen": "operator mindset",
        "team": "team-building thinking",
        "lease": "real-estate thinking",
        "background": "background self-disclosure",
    }
    seen = set()
    for kw, label in keywords.items():
        if kw in m.lower() and label not in seen:
            seen.add(label)
            score += 8
            reasons_bits.append(label)
    score = min(100, score)
    return score, ("Substantive: " + ", ".join(reasons_bits)) if reasons_bits else "Substantive message"


def score(inquiry: dict) -> FranchiseScore:
    """Score a validated franchise inquiry. Inquiry shape mirrors FranchiseIn."""
    capital = inquiry.get("capital") or ""
    timeline = inquiry.get("timeline") or ""
    city = inquiry.get("city") or ""
    message = inquiry.get("message") or ""

    cap_pts = _CAPITAL_FIT.get(capital, 30)
    tim_pts = _TIMELINE_URGENCY.get(timeline, 30)
    city_pts, city_reason = _score_city(city)
    text_pts, text_reason = _score_text(message)

    # Weighted: capital × 0.30, timeline × 0.30, city × 0.20, text × 0.20
    total = round(cap_pts * 0.30 + tim_pts * 0.30 + city_pts * 0.20 + text_pts * 0.20)

    if total >= 75:
        label = "hot"
    elif total >= 50:
        label = "warm"
    else:
        label = "cool"

    reasons = [
        f"Capital fit ({capital}): {cap_pts}",
        f"Timeline ({timeline}): {tim_pts}",
        f"City: {city_pts} — {city_reason}",
        f"Message: {text_pts} — {text_reason}",
    ]

    return FranchiseScore(
        total=total,
        capital=cap_pts,
        timeline=tim_pts,
        city_tier=city_pts,
        text_quality=text_pts,
        label=label,
        reasons=reasons,
    )
