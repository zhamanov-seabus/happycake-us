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

| # | Channel | $ | CAC | Expected revenue | Why & A/B plan |
|---|---|---:|---:|---|---|
| 1 | **B2B office-box outreach** (WhatsApp Business + LinkedIn DM) | **$150** | ~$38 / converted office | $1,500–2,500 | 20 cold reaches in Sugar Land's dental/realty/accounting cluster (5–30 staff each). Agent-driven: the wrapper composes a 3-step outreach sequence (intro → sample-box offer → weekly-box quote) in brandbook voice, queues each as an owner-approval card on `@happy_cake_owner_bot` via the wrapper's existing approval flow ([wrapper/src/marketing.py](../wrapper/src/marketing.py) `queue_for_owner_approval`); owner taps Approve before `whatsapp_send` fires. Convert 3–5 offices to weekly recurring at $120/wk. **A/B subject:** "Friday office boxes for [company]" vs. "Cake for the team this Friday?" — first 10 sends split 50/50. ROI: 10–17×. |
| 2 | **Repeat-customer WhatsApp campaign** | **$100** | ~$1.67 / reactivation | $1,200–1,500 | 600 prior customers across 2025-11 to 2026-04, no current re-engagement loop. $5-off promo code `BACK5` valid on whole cake or office box. Assumed redemption 10% (industry-typical for 6-mo dormant). **Live measurement:** redemption tracked via `BACK5` code in Square; if week-1 rate < 6% we pause and rewrite the message. Cheapest channel because the audience already converted once. ROI: 12–15×. |
| 3 | **Meta Ads — celebration-window targeting** | **$150** | ~$7.50 / order | $1,000–1,200 | Geo: 10mi around Sugar Land (77479/77478/77498), women 25–65, life-events triggers (birthday/anniversary windows). CPL ~$4, CVR ~10% → ~20 orders × $55 AOV. **A/B creative:** (A) carousel of `cake "Honey"` whole + pistachio roll on linen vs. (B) 15s UGC vertical video of a slice being plated. Promo code `CAKE5` for attribution. ROI: 7–8×. |
| 4 | **Google reviews funnel** (incentive at pickup) | **$50** | ~$10 / incremental order | $300–500 | 1,842 profile views → only 41 calls (12% action rate is the funnel leak, not impressions). Move from rank 5–8 to top-3 local pack via 25 fresh reviews/month. $50 = free slice with each verified review × 25. Promo code `REVIEW` redeemed at counter. Compounds — every month of reviews helps the next month's discovery. |
| 5 | **Boosted IG — Friday bake-batch only** | **$50** | ~$4.17 / order | $200–400 | Brandbook cadence: Mondays classics, Wednesdays seasonal, **Fridays bake-batch**. Boost the Friday post when supply is highest; other days stay organic. $14 × 4 boosts/month. Promo code `FRESH` for slice attribution. Drives same-day counter visits. |
| | **Total** | **$500** | weighted avg ~$10 | **$4,200–6,100** | **8.4×–12.2× revenue / $500.** |

**LTV note for line 2:** A reactivated repeat customer doesn't return once. Sandbox sales history shows 676 orders/mo on roughly 600 unique-name customers across 6 months — meaning the average customer in the file orders multiple times per period. Treating each $5-off redemption as 1 order undercounts. A more honest model: each reactivation has an effective LTV of ~3 follow-up orders × $25 = $75 over the next 90 days, putting line 2's true ROI closer to 30× than 12×. We hold the table at the conservative number until the BACK5 cohort matures.

## Why this beats a flat "spend it all on Meta"

- **Meta-only on a $500 budget at $4 CPL gets you 125 leads.** At a generous 8% CVR that's 10 orders. Even at $55 AOV that's $550 — barely 1.1×.
- **The 10× target requires concentrating on conversions that already exist** (repeat customers) and on customers with structurally higher AOV (offices, whole-cake celebrations).
- **Slices stay important** — they're the discovery product — but slice orders are *outcomes* of the channels above, not a budget line item.

## What we're explicitly NOT doing

- **No third-wave coffee push.** Brandbook §1: "We are not a candy store." Coffee is a quiet companion to dessert; spending on it would dilute brand.
- **No exotic flavour launches.** Same source: "Traditional, time-tested cakes — not exotic flavours of the week."
- **No paid Google Search (Google Ads).** Considered, rejected for this $500 cycle. GB profile views (1,842) tell us we already get organic search traffic; the leak is **action rate** (12%), not impressions. Search ads at a Houston-metro bakery CPC of ~$3.50 and 8% landing-page CVR would be ~$44 CAC — 4× our weighted blended CAC and worse than every channel in the table. The reviews funnel (line 4) attacks the same funnel leak structurally, for less money. **Revisit trigger:** if action rate stays below 12% after 60 days of running the reviews funnel, or if a competitor enters the local pack, we pilot a $50 branded-search test next cycle.
- **No influencer pay-to-play.** Brandbook §3 audience = traditional families. Influencer-driven discovery doesn't match the customer.

## Weekly content calendar (per brandbook §5 cadence)

| Day | IG | Google Business Profile | Other | Spend |
|---|---|---|---|---|
| Mon | Classics post — `cake "Honey"`, `cake "Napoleon"` | GB Update post mirroring the IG caption with a "Call now" CTA | — | $0 |
| Tue | Customer photo / repost (with permission) | GB Q&A monitor — agent answers any pending question within 4 hours | — | $0 |
| Wed | Seasonal / new on the counter | GB Update post + product photo upload to the catalog gallery | — | $0 |
| Thu | Behind-the-bake — kitchen photo (Stories only) | GB review responses — agent drafts replies to all new reviews; owner approves via Telegram | — | $0 |
| Fri | Today's bake-batch — what's available **(boosted)** | GB Offer post tagged `FRESH` for slice attribution | — | $14 |
| Sat | Saturday slice — single-serving close-up | GB photo upload — fresh storefront shot | — | $0 |
| Sun | Family table — whole-cake setting shot | GB analytics pull (`gb_get_metrics`) feeds the Sunday owner digest | Owner digest via `marketing_report_to_owner` | $0 |

The GB column is its own commitment: 1 Update/post 3× per week (Mon/Wed/Fri), Q&A within 4h, review responses within 24h, and a weekly metrics read into the Sunday owner digest. This is what moves us from rank 5–8 to top-3 local pack — the reviews funnel (line 4) feeds it; the cadence keeps the profile alive.

## Attribution & measurement

A plan without an attribution path is a guess with extra steps. Every dollar spent here is tied to a unique signal we can read back from sandbox state.

### Per-channel attribution

Every promo code is written into the order's `items[].note` field at `square_create_order` time, so it's readable back from `square_recent_orders` and `square_recent_sales_csv` without depending on Square discount features the sandbox doesn't simulate.

| Channel | Promo code | UTM tag | Counter / dashboard signal |
|---|---|---|---|
| B2B office-box outreach | `OFFICE` | `?utm_source=wa-outbound&utm_medium=dm&utm_campaign=office-q2` | `square_recent_orders` items with `note` containing `OFFICE`; cross-checked against the outreach card history in `evidence/log.jsonl` |
| Repeat-customer WhatsApp | `BACK5` | `?utm_source=wa-broadcast&utm_medium=text&utm_campaign=back5-may` | `square_recent_orders` items with `note` containing `BACK5`; redemption rate = matched orders / broadcast send count |
| Meta Ads — celebration | `CAKE5` | `?utm_source=meta&utm_medium=carousel&utm_campaign=celeb-window` (variant A) `&utm_content=carousel-a` / (variant B) `&utm_content=video-b` | `square_recent_orders` items with `note` containing `CAKE5`; landing-page hits split by `utm_content` via the Astro `/api/event` beacon |
| Google reviews funnel | `REVIEW` | n/a (counter redemption only) | `gb_list_reviews` count delta MoM via `gb_get_metrics`; counter redemptions in `square_recent_orders` items with `note` containing `REVIEW` |
| Friday IG boost | `FRESH` | `?utm_source=ig&utm_medium=boosted&utm_campaign=friday-batch` | `square_recent_orders` items with `note` containing `FRESH`; reach proxied by Friday counter-order delta vs. the prior 4 Fridays' baseline |

### Closed-loop controls

- **Campaign IDs are first-class.** `marketing_create_campaign` returns an ID, which we persist in the campaign's evidence record. Every subsequent `marketing_adjust_campaign`, `marketing_route_lead`, and `marketing_get_campaign_metrics` call is keyed off that ID.
- **Goal metric:** orders or leads, not impressions. Impressions inform but never trigger reallocations on their own.
- **Pace threshold:** if at day 14 a campaign is below 50% of expected revenue pace, we call `marketing_adjust_campaign` with the rationale and reroute spend. This is implemented in [scripts/marketing-sync.py](../scripts/marketing-sync.py).
- **Promo-code redemption gate:** Sunday automation queries Square for redemption counts per code. If a code is below 50% of expected redemption at day 7, the broadcast/post is rewritten and re-sent the next cycle.
- **Owner digest:** every Sunday 18:00 CT, the agent calls `marketing_report_to_owner` and posts a Telegram summary to `@happy_cake_owner_bot` showing spend, redemptions per code, top performer, worst performer, and the planned reroute. The owner has 24h to redirect before reroute auto-applies.
- **Audit trail:** every campaign create / adjust / report call is appended to `evidence/log.jsonl` with the sandbox-side ID, so a fresh evaluator clone reproduces the full marketing loop via [scripts/seed.sh](../scripts/seed.sh) → [scripts/seed-evaluator-evidence.py](../scripts/seed-evaluator-evidence.py).

## Scaling path (when revenue allows)

1. First $500 → execute as above, prove the office-box and repeat-customer channels.
2. Second $500 (next month) → double-down on whichever of (1) and (2) had higher CAC/AOV ratio.
3. Third $500 → start a referrals program: each customer gets a code, $5 off for them, $5 credit for the friend.
4. After three months: bring in light brand display (out-of-home in two key Sugar Land HEB grocery exits) only if the owner wants to.
