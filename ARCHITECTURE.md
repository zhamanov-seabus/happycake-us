# Architecture

## Big picture

```
                      ┌──────────────────────────────────────┐
                      │            Sandbox MCP               │
                      │ www.steppebusinessclub.com/api/mcp   │
                      │  (Square / WhatsApp / Instagram /    │
                      │  Google Business / Marketing /       │
                      │  Kitchen / World / Evaluator)        │
                      └──────────┬─────────────────────┬─────┘
                                 │                     │
                            forwards                   │
                            inbound                    │ outbound
                            webhooks                   │ tool calls
                                 │                     │
                  ┌──────────────▼─────────────────────▼────────────┐
                  │          wrapper/  (FastAPI on :8000)           │
                  │  ┌────────────────────────────────────────┐     │
                  │  │ /webhook/instagram  /webhook/whatsapp  │     │
                  │  │ /chat               /health            │     │
                  │  └──────────────────┬─────────────────────┘     │
                  │                     │                            │
                  │            ┌────────▼──────────┐                 │
                  │            │   agent.py        │  one prompt,    │
                  │            │   claude_runner   ◄──── one agent  │
                  │            └────────┬──────────┘                 │
                  │                     │  decision JSON              │
                  │            ┌────────▼──────────┐                 │
                  │            │   owner_bot       │                 │
                  │            │   (@happy_cake_   │                 │
                  │            │    owner_bot)     │                 │
                  │            └────────┬──────────┘                 │
                  │                     │ Telegram long-poll         │
                  └─────────────────────┼─────────────────────────────┘
                                        │
                                  ┌─────▼─────┐
                                  │ The owner │
                                  │ (Askhat)  │
                                  └───────────┘
```

The user (operator) sees only the **owner Telegram bot**. Customers see only their own channel (Instagram DM, WhatsApp, or the website chat widget). Everything else is plumbing.

---

## Components

### 1. Static site — `web/`

- Built with **Astro 5** in `output: 'static'` mode. Deploys as a flat folder; no Node runtime needed in production.
- **Single source of truth at [`data/catalog.yml`](data/catalog.yml).** Astro reads it at build time via [`web/src/lib/catalog.ts`](web/src/lib/catalog.ts).
- Pages: home, catalog, per-product (`product/[slug]/`), policies, about. Plus three machine surfaces: `/api/catalog.json`, `/sitemap.xml`, `/llms.txt`.
- JSON-LD: `LocalBusiness` in the layout (every page), `Product`+`Offer` per product, `FAQPage` on policies.
- On-site assistant: [`web/src/components/Assistant.astro`](web/src/components/Assistant.astro) — sticky chat widget, posts to wrapper `/chat`.

### 2. Wrapper service — `wrapper/`

- **FastAPI** on port 8000. Three input surfaces:
  - `POST /webhook/instagram` — receives forwarded events from `instagram_register_webhook`
  - `POST /webhook/whatsapp` — receives forwarded events from `whatsapp_register_webhook`
  - `POST /chat` — on-site widget on the static site
- Plus a built-in **Telegram polling task** in the FastAPI lifespan, for the owner bot.

#### Module map

| File | Responsibility |
|---|---|
| `src/app.py` | FastAPI app + routes + lifespan that boots the bot. |
| `src/agent.py` | Orchestration: webhook → claude_runner → owner_bot.send_handoff → on_owner_decision → mcp_client. |
| `src/claude_runner.py` | Subprocess-invokes `claude -p` with our system prompt + the live catalog injected. Parses JSON output. |
| `src/owner_bot.py` | Telegram bot via `python-telegram-bot`. Inline keyboards (`order:approve:<id>`, `order:edit:<id>`, `order:reject:<id>`). |
| `src/mcp_client.py` | Direct JSON-RPC POST to the sandbox MCP. Used for owner-decision side effects (create order, create kitchen ticket, send DM). |
| `src/evidence.py` | Append-only JSONL writer. Every meaningful event logs one line. |
| `src/config.py` | `.env` loading. |
| `src/prompts/system.md` | The agent system prompt — brand rules, output schema, hard rules. |

### 3. Sandbox MCP

50+ tools across 8 namespaces. We use these in the runtime path:

| Tool | Where called from | Purpose |
|---|---|---|
| `square_create_order` | `agent.on_owner_decision` (after Approve) | Creates the simulated POS order |
| `kitchen_create_ticket` | same | Hands the order off to the kitchen |
| `square_update_order_status` | (future) | Status transitions |
| `instagram_send_dm` | `agent._reply_to_customer` and `app.webhook_instagram` (FAQ inline replies) | Outbound IG reply |
| `whatsapp_send` | `agent._reply_to_customer` and `app.webhook_whatsapp` | Outbound WhatsApp reply |
| `instagram_register_webhook` / `whatsapp_register_webhook` | `scripts/register-webhooks.sh` | Boot-time setup |
| `square_list_catalog` | (build seed only) | Catalog reality check at scaffold time |
| `kitchen_get_capacity` | (agent context) | Future — surface to system prompt |

For marketing (offline, in `marketing/plan.md`): `marketing_get_sales_history`, `marketing_get_margin_by_product`, `gb_get_metrics`. Plan generation uses these once; runtime doesn't.

For evaluation (called at submission time): `evaluator_generate_team_report` with `repoUrl` + `websiteUrl`.

---

## Routing — the decision tree

For every customer message, after `claude_runner.respond_to_message`:

```
agent decision JSON
  ├── intent: "smalltalk" or "faq", needs_owner_approval: false
  │     → reply directly on the customer channel via instagram_send_dm / whatsapp_send
  │     → log customer_reply event
  │
  ├── intent: "order_intent", needs_owner_approval: false (rare)
  │     → still send owner card (always confirm orders)
  │     → on Approve: square_create_order + kitchen_create_ticket + customer reply
  │
  ├── intent: "order_intent" or "complaint" or "escalate"
  │     → owner_bot.send_handoff with structured card
  │     → wait for human button click
  │     → Approve / Edit / Reject branches
  │
  └── any path
        → write all events to evidence/log.jsonl
```

### Why claude -p (not Agent SDK)

Per hackathon §4, the only allowed runtime is **Claude Code CLI in headless mode**. We comply: `wrapper/src/claude_runner.py` shells out to `claude -p` for every customer message. The CLI picks up `.mcp.json` from the repo root, so the agent has tool access to the sandbox at runtime.

We considered structuring the agent as multiple `claude -p` calls (classify → check inventory → reply), but cold-start cost is ~2–5s per invocation. Instead we **pack one prompt** with: brandbook excerpt, live catalog, output schema. One call returns the structured decision. Median latency: 5–8s.

---

## Evidence log schema

`evidence/log.jsonl` — one JSON object per line, append-only.

```json
{
  "ts": "ISO 8601 UTC",
  "type": "webhook_in" | "claude_call" | "mcp_call" | "owner_handoff"
        | "owner_decision" | "customer_reply" | "error" | "demo_step",
  "source": "instagram" | "whatsapp" | "website" | "telegram" | "system",
  "payload": { /* event-specific */ }
}
```

The evaluator can grep this single file for any event type and replay the flow.

---

## Telegram bots — inventory

Per submission §8:

| Bot | Role | Counts as | Token |
|---|---|---|---|
| `@happy_cake_owner_bot` | Owner UI: receives order cards with Approve / Edit / Reject inline keyboard. `/start`, `/today`. | One agent's owner-facing UI (per brief §4 "one bot per agent") | `TELEGRAM_BOT_TOKEN` in `.env` |

We do **not** ship a customer-facing Telegram bot. Customers reach us via Instagram, WhatsApp, or the website chat widget — Telegram is the operator's surface, per brief §4.

---

## Owner-decision flow in detail

```
Owner DMs the bot in Telegram (one-time /start)
     ↓
Customer message arrives
     ↓
Wrapper calls claude -p, parses JSON
     ↓
agent.handle_customer_message → owner_bot.send_handoff(handoff)
     ↓
Bot posts a card to TELEGRAM_OWNER_CHAT_ID with three inline buttons
     ↓
Owner taps a button (callback_data = "order:approve:<id>")
     ↓
owner_bot._on_callback fires registered handlers
     ↓
agent.on_owner_decision(order_id, "approve", handoff):
     ├─ build square_items (snake_case → camelCase boundary)
     ├─ mcp_client.call("square_create_order", …)
     ├─ extract id from response.order.id
     ├─ build kitchen_items (variation_id → kitchen_product_id via catalog)
     ├─ mcp_client.call("kitchen_create_ticket", …)
     └─ _reply_to_customer (instagram_send_dm or whatsapp_send)
     ↓
Card edited in Telegram to show the verb chosen
Evidence log gets owner_decision + mcp_call entries
```

Edit and Reject are similar but skip the order/ticket creation and send a different customer-side message.

---

## Why each evaluation rubric item is covered

| Rubric (out of 100 + 15 bonus) | Where in the codebase |
|---|---|
| Functionality (20) | `wrapper/` end-to-end + `scripts/demo.sh` reproducible flow |
| Agent-friendly (15) | `web/public/llms.txt`, `/api/catalog.json`, `/sitemap.xml`, JSON-LD in `web/src/layouts/Layout.astro` and product pages |
| Assistant capability (15) | `wrapper/src/prompts/system.md` grounded in `data/brandbook.md`; on-site widget at `web/src/components/Assistant.astro` |
| Code quality (15) | One source of truth (`data/catalog.yml`); explicit boundary at `mcp_client`; structured evidence log |
| Operator usability (15) | `@happy_cake_owner_bot` with three-tap approval; `/today` for pending; HTML-formatted cards |
| Business analysis (10) | `marketing/plan.md` grounded in real sandbox sales (6 mo) and margins; concrete CAC math |
| Innovation bonus (+15) | One pre-packed `claude -p` call (latency optimisation); evidence/log.jsonl for evaluator audit; agent-side variation_id grounding via inline catalog block |

---

## Sample launchd plist (optional, for an always-on operator daemon)

If you want the owner bot to survive restarts and tunnel disconnects, drop this at `~/Library/LaunchAgents/us.happycake.wrapper.plist` and `launchctl load` it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>us.happycake.wrapper</string>
  <key>ProgramArguments</key><array>
    <string>/Users/<you>/code/happycake-us/scripts/run-wrapper.sh</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/<you>/code/happycake-us</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/happycake-wrapper.log</string>
  <key>StandardErrorPath</key><string>/tmp/happycake-wrapper.err</string>
</dict></plist>
```

For Linux, an equivalent systemd unit lives in `deploy/` (TODO if needed).

---

## Innovation log (what we did differently)

The brief's **Innovation and Depth Spotter** pass looks for surprising original moves. Here is what's deliberately non-obvious in this submission, with why each choice came up.

1. **One pre-packed `claude -p` call instead of a chain.** Every customer message goes through ONE invocation that already contains brandbook + live catalog + channel rules + output schema. Latency: ~5–8s instead of 15–25s with a classify→inventory→reply chain. Trade-off: the agent has to do everything in one decision; that's why the system prompt is explicit about JSON-only output and intent classification.
2. **Channel-aware closing rules** baked into the prompt. The brandbook closes with "Order on the site at happycake.us or send a message on WhatsApp." That makes sense on IG/WA — but on the on-site chat widget the customer is *already* on the site, and there's no real WhatsApp number in this build. The prompt distinguishes channels so the website agent never tells customers to leave the site.
3. **Edit verb that completes**, not a placeholder. After ✏️ Edit, the bot prompts the owner with a `ForceReply`; whatever they type next gets relayed to the customer on their channel (IG / WA / website widget polling). The Telegram-only-owner-UI rule is preserved while keeping the customer's experience un-broken.
4. **Polling fallback for Cloudflare quick-tunnel SSE buffering.** Cloudflare's free quick tunnels buffer `text/event-stream` indefinitely. We kept the SSE endpoint for clients on un-buffered proxies but the chat widget polls `/order/{id}` every 2.5s. Both code paths share one `order_events` pub/sub.
5. **Webhook ack-immediately + async processing.** Sandbox forwarder times out fast; `claude -p` takes seconds. Webhooks log + spawn an `asyncio.create_task` and return 202 in milliseconds, which makes the sandbox happy without compromising agent correctness.
6. **Meta envelope handling for both shapes.** Sandbox forwards Instagram comments via `entry[].changes[].field=='comments'` and DMs via `entry[].messaging[].message.text` — the WhatsApp Business API and Messenger Platform have different shapes. `_extract_message` and `_extract_comment` cover both.
7. **`/configure` as a deterministic agent surface.** Instead of forcing an external AI to scrape the `/custom/` HTML form, the wrapper exposes a `POST /configure` that returns a structured recommendation with allergen warning, lead time, and a next-step instruction pointing at `/chat`.
8. **Marketing creatives use the same one-prompt pattern.** `/marketing/draft` runs `claude -p` against the brandbook to produce a JSON draft (caption + image_role + image_index + rationale). The owner taps Approve in Telegram and only THEN the post publishes — staying within the brief's "owner approval before publish" constraint.
9. **One source of truth for catalog drives three consumers.** `data/catalog.yml` feeds the Astro site (build-time read), `/api/catalog.json` (machine-readable), and the agent system prompt (live catalog block injected per request). No risk of drift; renaming a variation_id changes everything in one commit.
10. **Build-time MCP fetch for the agent-friendly inventory API.** `web/src/lib/sandbox.ts` calls `square_get_inventory` and `kitchen_get_capacity` at `astro build` time — so `https://happycake.us/api/inventory.json` returns live data without a runtime server, and the homepage capacity badge reflects sandbox state on every Pages deploy.

---

## What we deliberately did not build

- **WhatsApp Business API integration** beyond the sandbox simulator (per brief §4, real WhatsApp prod access is forbidden).
- **Custom-cake decoration intake forms.** Brandbook §1: "We are not custom cakes." Custom orders go through the same agent path, just always with `needs_owner_approval: true`.
- **Kazakh / Russian language replies.** Brandbook §2: "Always English."
- **A second agent.** One prompt, one `claude -p` call, one decision per message — keeps the runtime within the brief's "one bot per agent" rule and avoids inter-agent orchestration that the Agent SDK would solve and we can't use.
