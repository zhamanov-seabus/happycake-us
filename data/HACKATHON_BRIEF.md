# Steppe Business Club Hackathon brief

Happy Cake US, Sugar Land, Texas

Deadline: May 10, 10:00 CT

Use this file as source material for your Claude Code agent. Paste it into the project context, add it to your repo, or ask your agent to read it before planning the build.

## 1. Business context

Happy Cake US is a local cake and dessert business in Sugar Land, Texas.

Current situation:

- Monthly revenue is roughly $15K-20K.
- Most operations are manual.
- Walk-in sales are the main channel.
- WhatsApp exists, but replies and order intake depend on the owner.
- Instagram works mostly like a window display.
- The website is a placeholder.
- Marketing budget is $500 per month.

The business needs more orders, faster replies, better handoff to kitchen/cashier, and a clearer picture of what marketing actions bring customers.

Your work should feel useful for an owner who has real customers, limited time, and limited budget.

## 2. Main task

Build an AI-assisted sales and operations system for Happy Cake US.

The system should help a customer move from interest to order, and help the owner understand what happened.

A good flow might look like this:

1. Customer sees a cake on Instagram.
2. Customer sends a DM or WhatsApp message.
3. Assistant answers in Happy Cake voice.
4. Customer asks about flavors, dates, custom text, size, price, pickup, delivery, or allergens.
5. Assistant checks catalog, inventory, policies, kitchen constraints, and order rules through the sandbox/MCP layer.
6. Assistant takes the order to intent, escalates where needed, and creates a clear handoff for owner/kitchen/cashier.
7. Owner gets a useful Telegram update.
8. System leaves evidence in logs/state so the evaluator can verify what happened.

## 3. Outcomes to cover

You do not need to solve everything equally. Pick a strong vertical slice and make it work.

### Website / storefront

Build happycake.us as a real sales site.

It should have:

- catalog;
- prices;
- product photos;
- order path;
- pickup/delivery or availability logic;
- clear policies;
- useful content for customers;
- structure that AI agents can read without brittle scraping.

The winning website may become the future production site for Happy Cake US.

### Agent-friendly website

A customer-side AI agent should be able to understand the site.

That means:

- product data is readable;
- prices and constraints are clear;
- policies are explicit;
- order-intent path is discoverable;
- pages are structured enough for automated browsing and extraction.

### On-site assistant

The site can include an embedded assistant.

Useful scenarios:

- product guidance;
- custom cake consultation;
- event planning;
- complaint handling;
- order status question;
- escalation to owner.

The assistant must use sandbox evidence and site data. It should not invent facts.

### WhatsApp

WhatsApp should answer quickly and in brand voice.

Useful scenarios:

- menu questions;
- date availability;
- custom cake request;
- order intake;
- human handoff;
- kitchen/cashier note.

### Instagram

Instagram should become a sales channel.

Useful scenarios:

- content plan;
- post/story ideas;
- replies to comments;
- DM order capture;
- routing interested customers into an order path;
- using photo assets and brand voice correctly.

### Marketing: $500 per month

The marketing challenge is simple: make $500 work as hard as possible.

Your system should explain how to spend the budget across channels such as:

- Meta Ads;
- Google Ads;
- boosted posts;
- local search;
- organic content;
- review generation;
- follow-up and repeat orders.

Use margin, order value, conversion assumptions, and local-customer logic. Do not write generic marketing advice.

## 4. Runtime rules

The runtime is fixed for this hackathon.

Allowed:

- Claude Code CLI;
- local execution on the operator's machine;
- Claude Opus 4.7 through the participant's own Claude Max subscription;
- Telegram as owner-facing UI;
- one bot per agent if the system has multiple agents;
- `claude -p "<prompt>"` as the headless bridge;
- ngrok or Cloudflare Tunnel for inbound webhooks to local machine;
- hosted sandbox/MCP endpoints provided by the hackathon.

Not allowed:

- Claude Agent SDK;
- LangGraph;
- CrewAI;
- n8n;
- other LLM providers for the core runtime;
- real Happy Cake credentials;
- real payment credentials;
- real WhatsApp/Instagram/Square production access.

Bring your own Claude Max subscription. The hackathon does not provide Claude credits, API tokens, or paid seats.

## 5. Standard runtime pattern

Most teams will have a pattern like this:

```bash
# 1. WhatsApp or Instagram webhook hits ngrok / Cloudflare Tunnel URL.
# 2. Telegram bot wrapper receives the event, or owner messages the bot directly.
# 3. Wrapper shells out to Claude Code CLI in headless mode.
# 4. Claude uses project files, prompts, MCP config, and sandbox data.
# 5. Wrapper sends the response back to the customer channel and logs to Telegram.
# 6. If approval is needed, wrapper asks the owner in Telegram.

claude -p "Customer wrote in WhatsApp: 'Do you have honey cake today?'
Use the inventory MCP to check, reply in Happy Cake voice, and if the customer wants to order, create the order handoff."
```

You can implement wrappers in Python, TypeScript, or another practical language.

## 6. Sandbox and MCP

Each team gets isolated sandbox access.

The sandbox can simulate:

- Square/POS;
- WhatsApp;
- Instagram;
- Google Business;
- marketing actions;
- kitchen/production state;
- world/customer events;
- evaluator evidence.

Treat the sandbox as the source of truth for this hackathon.

Do not use real business credentials. Do not ask organizers for production access.

## 7. Assets

Use the approved Happy Cake materials.

Important links:

- Brandbook Markdown: `/hackathon-assets/HCU_BRANDBOOK.md`
- Asset pack and photos: `/hackathon/brief/assets`
- Sandbox page: `/hackathon/brief/sandbox`

The brandbook has voice, colors, content rules, and usage notes.

## 8. Submission

Deadline: May 10, 10:00 CT.

Push the final commit before the deadline.

Submit a public Git repository.

Your repo should include:

- README with setup from a fresh clone;
- ARCHITECTURE.md with agents, routing, MCP usage, owner-bot mapping;
- .env.example with placeholders only;
- website/storefront instructions;
- production or local deploy notes;
- business-impact hypothesis, including the $500 marketing budget case;
- agent-friendly website notes;
- on-site assistant test script;
- list of Telegram bots and what each bot does.

Never commit secrets.

## 9. Evaluation

The evaluator will clone the repo and run the system using your instructions.

It will check:

- website/storefront quality;
- customer path to order intent;
- agent-friendly structure;
- use of sandbox/MCP evidence;
- Telegram owner flow;
- WhatsApp/Instagram/customer-channel behavior;
- marketing plan and budget logic;
- kitchen/cashier handoff;
- README and architecture clarity;
- security hygiene;
- whether the system can be brought closer to a real Happy Cake deployment after the hackathon.

Evidence matters. Logs, MCP calls, screenshots, state changes, and reproducible flows help more than claims.

### Bonus points

Core score is 100 points. Extra functions can add up to +15 bonus points when they solve real Happy Cake business pains after the core brief is already strong.

Bonus areas:

- up to +5 for solving a real business pain: custom cake intake, complaints/refunds, allergy-safe communication, production capacity, repeat customers, reviews, abandoned orders;
- up to +5 for production readiness: clean deploy, mobile performance, admin/operator view, audit trail, failure handling, safe owner handoff;
- up to +5 for growth upside: lead scoring, local SEO, referrals, WhatsApp follow-up, upsell logic, marketing budget optimization.

Bonus cap:

- Core score 80+ — eligible for up to +15 bonus points;
- Core score 60-79 — maximum +5 bonus points;
- Core score below 60 — bonus points do not apply.

Bonus cannot replace the core brief. Maximum total score is 115.

## 10. Suggested way to use Claude Code

Start with planning:

```bash
claude -p "Read HACKATHON_BRIEF.md and the Happy Cake brandbook. Propose a minimal architecture for a 24-hour build. Pick one strong vertical customer-to-order scenario. Keep the runtime rules."
```

Then ask Claude Code to create a small execution plan:

```bash
claude -p "Based on HACKATHON_BRIEF.md, write a build plan with files, components, bots, MCP calls, tests, and demo script. Prioritize a working end-to-end flow."
```

Use short loops:

- build one path;
- test it;
- log evidence;
- improve the weakest step;
- update README and ARCHITECTURE.md as you go.

## 11. Practical advice

Pick one customer journey and make it real.

Good journeys:

- Instagram DM to cake order intent;
- WhatsApp inquiry to kitchen handoff;
- website visitor to custom cake consultation;
- owner asks Telegram bot what to post today and why;
- customer complaint handled with escalation and evidence.

Keep the scope small enough to finish.

A working, narrow system is easier to evaluate than a broad concept with missing pieces.

## 12. Final checklist

Before submitting:

- fresh clone works;
- README setup is clear;
- .env.example has placeholders only;
- no secrets in repo;
- website runs;
- bot/wrapper runs;
- MCP/sandbox calls are documented;
- demo script exists;
- ARCHITECTURE.md explains the system;
- submission form has the correct repo link;
- final commit is before May 10, 10:00 CT.
