"""Tests for franchise inquiry scoring."""
from __future__ import annotations

from happycake_wrapper import franchise_score


def test_hot_lead_high_capital_short_timeline_tier1_substantive():
    """Houston operator with 250-400K, 0-3mo, substantive message → hot."""
    res = franchise_score.score({
        "capital": "250-400k",
        "timeline": "0-3mo",
        "city": "Houston",
        "message": ("I have 8 years of restaurant operating experience, looking for a target "
                    "neighborhood near the Galleria. Multi-unit appetite over 5 years."),
    })
    assert res.label == "hot"
    assert res.total >= 75
    assert "Houston" in res.reasons[2] or "Tier-1" in res.reasons[2]


def test_warm_lead_capital_raising_long_timeline():
    """Raising capital, 6-12mo, tier-2 city, brief message → warm or cool."""
    res = franchise_score.score({
        "capital": "raising",
        "timeline": "6-12mo",
        "city": "Lubbock",
        "message": "Interested.",
    })
    assert res.label in {"warm", "cool"}
    assert res.total < 75


def test_cool_lead_minimal_signal():
    """Just exploring, no capital plan, no message → cool."""
    res = franchise_score.score({
        "capital": "raising",
        "timeline": "exploring",
        "city": "Round Rock",
        "message": "",
    })
    assert res.label == "cool"
    assert res.total < 50


def test_unknown_city_does_not_crash():
    res = franchise_score.score({
        "capital": "250-400k",
        "timeline": "0-3mo",
        "city": "Some Random Town, AR",
        "message": "Operator background, multi-unit",
    })
    assert 0 <= res.total <= 100
    assert res.label in {"hot", "warm", "cool"}


def test_emoji_label_mapping():
    hot = franchise_score.FranchiseScore(80, 0, 0, 0, 0, "hot", [])
    warm = franchise_score.FranchiseScore(60, 0, 0, 0, 0, "warm", [])
    cool = franchise_score.FranchiseScore(30, 0, 0, 0, 0, "cool", [])
    assert hot.emoji() == "🔥"
    assert warm.emoji() == "🤝"
    assert cool.emoji() == "📩"
