# HappyCake — $500/month marketing plan

> The hackathon's marketing challenge: *make $500 work like $5,000.*
> This plan shows how, using real numbers from the sandbox.

## Numbers we're working from (sandbox)

Pulled from `marketing_get_sales_history`, `marketing_get_margin_by_product`, and `gb_get_metrics`:

| Month | Revenue | Orders | Avg ticket |
|---|---|---|---|
| 2025-11 | $14,820 | 612 | $24.22 |
| 2025-12 | $19,240 | 738 | $26.07 (holiday peak) |
| 2026-01 | $15,110 | 621 | $24.33 |
| 2026-02 | $16,890 | 668 | $25.28 |
| 2026-03 | $17,640 | 691 | $25.53 |
| 2026-04 | $18,320 | 724 | $25.30 |

**6-month average:** $17,003 revenue / 676 orders / $25.13 average ticket. Steady ~3% MoM growth.

| Product | Price | Margin | Gross profit/order |
|---|---|---|---|
| Honey cake slice | $8.50 | 68% | $5.78 |
| Pistachio roll | $9.50 | 64% | $6.08 |
| Whole honey cake | $55.00 | 62% | $34.10 |
| Custom birthday | $95.00 | 58% | $55.10 |
| Office dessert box | $120.00 | 60% | $72.00 |

**Google Business — last 30 days:** 1,842 profile views · 502 map views · 87 directions · 41 calls · 96 website clicks. **Action rate is only 12%** — the funnel from "saw us in search" to "got in touch" is the biggest leak.

**Implication:** the high-margin items (whole cakes, custom, office boxes) are where the $5,000 effect comes from. Slices alone won't get you 10x — even at 68% margin, 200 incremental slice orders = $1,156 gross profit. We need to weight spend toward orders that average $50+.

## Allocation — $500/month

| # | Channel | $ | Expected revenue impact | Why |
|---|---|---:|---|---|
| 1 | **B2B office-box outreach** (LinkedIn DM + WhatsApp follow-up) | **$150** | $1,500–2,500 | 20 cold reaches in Sugar Land's dental/realty/accounting cluster. Convert 3–5 offices to weekly recurring at $120 each. ROI: 10–17×. |
| 2 | **Repeat-customer WhatsApp campaign** | **$100** | $1,200–1,500 | 600 prior customers in 6mo, no current re-engagement. $5-off offer; ~10% redemption → 60 orders × $25. Cheapest channel we have because the audience already converted once. ROI: 12–15×. |
| 3 | **Meta Ads — celebration-window targeting** | **$150** | $1,000–1,200 | Geo-target 10mi around Sugar Land (zips 77479/77478/77498), women 25–65, life-events triggers (birthday/anniversary windows). Carousel of `cake "Honey"` whole + pistachio roll. CPL ~$4, CVR ~10% → ~20 orders × $55 AOV. ROI: 7–8×. |
| 4 | **Google reviews funnel** (incentive at pickup) | **$50** | $300–500 | 1,842 profile views → only 41 calls. Move from rank 5–8 to top-3 local pack by adding 25 fresh reviews/month. $50 = free slice with each verified review × 25. Compounds — every month of reviews helps the next month's discovery. |
| 5 | **Boosted IG — Friday bake-batch only** | **$50** | $200–400 | Brandbook cadence: Mondays classics, Wednesdays seasonal, **Fridays bake-batch**. Boost the Friday post (when supply is highest); other days stay organic. $14 × 4 boosts/month. Drives slice purchases that day. |
| | **Total** | **$500** | **$4,200–6,100** | **8.4×–12.2× revenue / $500.** |

## Why this beats a flat "spend it all on Meta"

- **Meta-only on a $500 budget at $4 CPL gets you 125 leads.** At a generous 8% CVR that's 10 orders. Even at $55 AOV that's $550 — barely 1.1×.
- **The 10× target requires concentrating on conversions that already exist** (repeat customers) and on customers with structurally higher AOV (offices, whole-cake celebrations).
- **Slices stay important** — they're the discovery product — but slice orders are *outcomes* of the channels above, not a budget line item.

## What we're explicitly NOT doing

- **No third-wave coffee push.** Brandbook §1: "We are not a candy store." Coffee is a quiet companion to dessert; spending on it would dilute brand.
- **No exotic flavour launches.** Same source: "Traditional, time-tested cakes — not exotic flavours of the week."
- **No paid Google Search.** GB profile views (1,842) tell us we already get search traffic. The leak is **action rate**, not impressions. Reviews fix that. Search ads would just buy clicks we already get for free.
- **No influencer pay-to-play.** Brandbook §3 audience = traditional families. Influencer-driven discovery doesn't match the customer.

## Weekly content calendar (per brandbook §5 cadence)

| Day | Post type | Channel(s) | Spend |
|---|---|---|---|
| Mon | Classics — `cake "Honey"`, `cake "Napoleon"` | IG, GB | $0 |
| Tue | Customer photo / repost (with permission) | IG | $0 |
| Wed | Seasonal / new on the counter | IG, GB | $0 |
| Thu | Behind-the-bake — kitchen photo | IG Stories | $0 |
| Fri | Today's bake-batch — what's available | IG (boosted), GB | $14 |
| Sat | Saturday slice — single-serving close-up | IG | $0 |
| Sun | Family table — whole-cake setting shot | IG | $0 |

## Measurement (what we'll actually watch)

We'll record campaign IDs from `marketing_create_campaign` and read back metrics with `marketing_get_campaign_metrics`. Each campaign:

- **Goal:** orders or leads (not impressions).
- **Threshold:** if at day 14 a campaign is below 50% of pace, we **pause and reroute** (`marketing_adjust_campaign`).
- **Per-week owner report:** the agent calls `marketing_report_to_owner` and posts the summary to `@happy_cake_owner_bot`. The owner has 24h to redirect.

## Scaling path (when revenue allows)

1. First $500 → execute as above, prove the office-box and repeat-customer channels.
2. Second $500 (next month) → double-down on whichever of (1) and (2) had higher CAC/AOV ratio.
3. Third $500 → start a referrals program: each customer gets a code, $5 off for them, $5 credit for the friend.
4. After three months: bring in light brand display (out-of-home in two key Sugar Land HEB grocery exits) only if the owner wants to.
