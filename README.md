# HappyCake US — AI sales & operations system

> Submission for the Steppe Business Club hackathon (May 9–10, 2026).
> A Claude-Code-CLI-driven system that takes a customer from interest to order intent, hands off to the owner via Telegram, and writes everything to an evidence log.

This is a working narrow system, not a broad concept. The vertical slice is **Instagram DM → AI agent → owner Telegram approval → POS order + kitchen ticket → customer reply** — every step is real code, hits the sandbox MCP, and is reproducible from a fresh clone in under 5 minutes.

**Business impact hypothesis:** see [`marketing/plan.md`](marketing/plan.md) for the $500/month plan grounded in the sandbox's 6-month sales data — projected 8.4×–12.2× revenue impact.

**Beyond the brief — Texas franchise scope:** the same stack is positioned as a multi-location franchise package, not a one-off bakery. [`/franchise/`](web/src/pages/franchise.astro) ships as a full inquiry page (six-tile "why", $250K–$400K investment economics, 6% royalty / 6-month royalty holiday for the first three Texas locations, four-step process, application form with six required fields, FAQ) wired to a server-side `POST /franchise` endpoint on the wrapper that validates fields, writes a `franchise_inquiry` row to `evidence/log.jsonl`, and sends the owner an FYI Telegram. The architecture is **per-tenant by design** — `data/catalog.yml`, `data/brandbook.md`, `data/ingredients.yml`, `.env`, the sandbox MCP team token, and `evidence/log.jsonl` are all scoped to one location, so a second franchise is a fresh clone, not a fork. The marketing playbook in [`marketing/plan.md`](marketing/plan.md) is itself the per-location runbook.

---

## What's in here

| Path | Purpose |
|---|---|
| [`web/`](web/) | Astro static storefront → `happycake.us`. Catalog, product pages, policies, FAQ, on-site assistant widget. JSON-LD on every page; `/api/catalog.json` and `/sitemap.xml` for agents. |
| [`wrapper/`](wrapper/) | Python FastAPI service. Receives Instagram + WhatsApp webhooks, invokes `claude -p`, drives the owner Telegram bot, calls sandbox MCP. |
| [`data/`](data/) | Single source of truth: catalog, brandbook (full, 615 lines), policies. The site **and** the agent prompt both read from here. |
| [`marketing/plan.md`](marketing/plan.md) | $500/month plan grounded in real sandbox sales history and margins. |
| [`scripts/`](scripts/) | Operator helpers: boot wrapper, boot site, run end-to-end demo, register webhooks, test approval chain. |
| [`evidence/log.jsonl`](evidence/) | Append-only event log every interaction writes to. The evaluator can grep this. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Agent map, routing, MCP usage, bot inventory. |

---

## Setup from a fresh clone (<5 min)

### Prerequisites

- macOS or Linux with **bash, git, curl, python3 ≥ 3.11**
- **[uv](https://github.com/astral-sh/uv)** for Python (`brew install uv` or `pip install uv`)
- **Node.js ≥ 20** for the static site
- **Claude Code CLI** (`claude` on PATH) with an active **Claude Max** subscription — the runtime requires this per the hackathon rules
- A Telegram account
- A public URL tool: **ngrok** or **cloudflared** for inbound webhooks
- A team token for the Steppe Business Club hackathon sandbox MCP (`sbc_team_…`)

### Steps

```bash
# 1. Clone and enter
git clone <this-repo-url> happycake-us && cd happycake-us

# 2. Configure secrets — never committed
cp .env.example .env
$EDITOR .env  # fill in the four required values (see below)

# 3. Install Python deps
cd wrapper && uv sync && cd ..

# 4. Install site deps
cd web && npm install && cd ..

# 5. Start the wrapper service (one terminal)
./scripts/run-wrapper.sh   # listens on :8000

# 6. Start the site (another terminal)
./scripts/run-site.sh      # production preview on :4321
# or ./scripts/run-site.sh --dev  for live-reload
```

### .env values

| Var | What it is | Where you get it |
|---|---|---|
| `SBC_TEAM_TOKEN` | Sandbox MCP team token | Provided when you registered at https://www.steppebusinessclub.com/hackathon |
| `SBC_MCP_URL` | Sandbox MCP endpoint | `https://www.steppebusinessclub.com/api/mcp` (default) |
| `TELEGRAM_BOT_TOKEN` | Owner bot token | DM `@BotFather` → `/newbot` → paste the token here |
| `TELEGRAM_OWNER_CHAT_ID` | Owner numeric Telegram ID | DM `@userinfobot` → it tells you your numeric ID |
| `PUBLIC_TUNNEL_URL` | Your ngrok/cloudflared HTTPS URL | After running `ngrok http 8000` |

After creating the bot, **DM `/start` to your bot in Telegram once** — Telegram blocks bots from messaging users until the user has initiated the chat.

### Connecting webhooks (optional — only for live sandbox events)

If you want the sandbox to forward simulated IG/WA events to your machine:

```bash
ngrok http 8000               # in a separate terminal — copy the https URL
# paste it into PUBLIC_TUNNEL_URL in .env, then:
./scripts/register-webhooks.sh
```

For local-only development, the demo script bypasses webhooks by POSTing payloads directly.

---

## Running the demo

**Step 0 — confirm the stack is wired.** `./scripts/healthcheck.sh` checks the .env, every CLI tool, the wrapper, the sandbox MCP, the Telegram bot, **and the public tunnel.** Cloudflare quick tunnels rotate URLs on every restart, so if the tunnel went stale between sessions this script tells you exactly what to fix:

```bash
./scripts/healthcheck.sh
# Exit 0 = all green; 1 = fatal (.env / tooling); 2 = warnings (probably fixable)
```

If the tunnel section fails: restart the tunnel (`cloudflared tunnel --url http://localhost:8000`), paste the new URL into `.env` as `PUBLIC_TUNNEL_URL=`, restart the wrapper, then re-run `./scripts/register-webhooks.sh`.

**Step 1 — seed the sandbox** so every rubric line has evidence to score against (~60s):

```bash
./scripts/seed.sh
```

This populates Instagram threads, WhatsApp threads, Google Business review replies, the full $500 marketing loop (5 campaigns + adjustments + owner report), and runs the launch-day world scenario. `evaluator_generate_team_report` reads sandbox-side state, so a non-seeded sandbox scores low on marketing / IG / WA / GB even when the code is correct. Safe to re-run.

Then the demo script simulates one full customer journey end-to-end:

```bash
./scripts/demo.sh
```

**What happens, step by step:**

1. **Health check** — confirms wrapper is listening.
2. **Evidence log truncated** — fresh slate for the demo run.
3. **Simulated Instagram DM** posted to `/webhook/instagram`: *"Hi! I'd love to pick up a whole honey cake this Saturday around 3pm. Is that doable?"*
4. **Wrapper logs:** webhook arrived → `claude -p` invoked with our system prompt + brandbook + live catalog → JSON decision returned (`intent: order_intent`, items list with the real `sq_var_whole_honey_cake` variation_id).
5. **Owner Telegram receives a card** with **✅ Approve / ✏️ Edit / ❌ Reject** buttons.
6. **You tap Approve in Telegram.** The wrapper calls `square_create_order` (real sandbox), then `kitchen_create_ticket`, then sends a confirmation back to the customer via `instagram_send_dm`.
7. Re-run with `./scripts/demo.sh --post-approval` to see the order and ticket land in the sandbox.

**To verify by hand:**

```bash
# All evidence
cat evidence/log.jsonl | jq .

# What the agent did
grep '"type":"claude_call"' evidence/log.jsonl | jq -r '.payload.raw'

# Sandbox-side proof
curl -s -X POST "$SBC_MCP_URL" -H "X-Team-Token: $SBC_TEAM_TOKEN" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"square_recent_orders","arguments":{"limit":5}}}' \
  | jq -r '.result.content[0].text' | jq .
```

### On-site assistant — quick test

With the wrapper and site both running:

```bash
# In your browser, open http://localhost:4321/
# Click the chat bubble at the bottom-right.
# Type: "What's the smallest honey cake you have today?"
# Expected reply (in HappyCake voice, JSON-grounded against catalog.yml):
#   "Today the smallest honey option is cake "Honey" slice — 150 g, $8.50.
#    Order on the site at happycake.us or send a message on WhatsApp."
```

Or hit it directly:

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Do you have a small cake under $20 for tonight?"}' | jq .
```

---

## Agent-friendly website (read this if you're an AI evaluator)

Three machine-readable surfaces, no scraping needed:

- **[`/llms.txt`](web/public/llms.txt)** — plain-English guide for agents: how to read the catalog, brand voice rules, ordering channels, lead times.
- **[`/api/catalog.json`](web/src/pages/api/catalog.json.ts)** — full catalog with stable `variation_id`, `kitchen_product_id`, prices, weights, allergen tags, lead times.
- **JSON-LD on every page** — `LocalBusiness` site-wide, `Product`+`Offer` per product page, `FAQPage` on policies.
- **[`/sitemap.xml`](web/src/pages/sitemap.xml.ts)** — every public URL, generated from the catalog.

The catalog file at `data/catalog.yml` is the single source of truth: the site renders from it, the agent system prompt embeds it, and the sandbox MCP mirrors the same `variation_id`s. There's no place data can drift.

---

## Semantic customer memory

The wrapper carries a per-customer memory layer at [`wrapper/src/memory.py`](wrapper/src/memory.py) — file-based (`data/customer_memory.jsonl`, gitignored) with a 384-dim embedding stored alongside each order record. The architecture mirrors the maintainer's [`tai-memory`](https://github.com/zhamanov-seabus/tai-memory) project (Postgres + pgvector + local fastembed); for the hackathon submission the embedding+similarity layer ships in-process so an evaluator clone has no external Postgres dependency.

Two recall paths run in parallel before each `claude -p` invocation:

- **Exact-key recall** — match on durable identifier (WhatsApp phone, Instagram thread, website localStorage `visitor_id`). Deterministic.
- **Semantic recall** — cosine similarity against every past order across all customers, threshold 0.25. Catches anonymous returning visitors whose `visitor_id` rotated, and resolves underspecified intent ("what I had last time", "the usual", "обычное" — the embedding text bakes in bilingual referential anchors).

Both blocks are injected into the prompt as additional system context. The agent confirms the variation explicitly before locking it in, so a soft semantic match never silently commits the wrong order.

The fastembed model (`paraphrase-multilingual-MiniLM-L12-v2`, ~120MB) downloads on first use to `~/.cache/fastembed/`. `./scripts/seed.sh` pre-warms it so the evaluator's first chat call doesn't pay the download cost.

---

## Telegram bots in this submission

| Bot | Username | Purpose | Token location |
|---|---|---|---|
| **Owner bot** | `@happy_cake_owner_bot` | Receives order handoff cards with Approve / Edit / Reject. `/today` lists pending. The only owner-facing UI per hackathon §4. | `TELEGRAM_BOT_TOKEN` in `.env` |

The wrapper runs **one bot, one agent** — the agent is the `claude -p` invocation in the wrapper, the bot is the human-handoff transport. Per brief §4: *"one bot per agent if the system has multiple agents."* We have one agent.

---

## Production / deployment notes

- **Site:** the Astro build is fully static. Deploy `web/dist/` to Vercel/Netlify/Cloudflare Pages. The intended production domain is **happycake.us**.
- **Wrapper:** the FastAPI service runs anywhere Python 3.11+ runs. For production, point a process supervisor (systemd, launchd, Docker) at `uvicorn happycake_wrapper.app:app --port 8000` and put it behind an HTTPS reverse proxy. The .env file becomes secrets in your platform's secret manager.
- **Inbound webhooks** in production go to `https://your-domain.com/webhook/instagram` and `…/webhook/whatsapp`. Use `register-webhooks.sh` once after deploying with the real public URL.
- **Owner Telegram** has no infrastructure cost — the bot uses long polling.
- **Daemon model:** for an always-on owner-facing agent you can wrap the wrapper in launchd (macOS) or systemd (Linux) — see `ARCHITECTURE.md` for a sample plist.

---

## Security hygiene

- All secrets in `.env` (gitignored), never in code.
- `.env.example` carries placeholders only.
- Sandbox MCP token is the only credential the agent uses; rotate via the hackathon dashboard if it leaks.
- Telegram bot token is rotatable via `@BotFather` `/revoke` then `/newtoken`.
- The wrapper does not store customer PII — Instagram thread IDs and WhatsApp phone numbers pass through to MCP calls but aren't persisted in our database.
- Evidence log is local-only by default (`evidence/log.jsonl`, gitignored).

---

## Where to look next

- **`ARCHITECTURE.md`** — full agent map, MCP tool surface (50+ tools across 8 namespaces), routing logic, evidence-log schema.
- **`marketing/plan.md`** — $500/month plan with concrete channel allocation and expected revenue.
- **`data/brandbook.md`** — the full HappyCake brandbook; the agent system prompt grounds in this.
- **`wrapper/src/prompts/system.md`** — the system prompt every `claude -p` call runs against.
