---
name: outreach-pilot
description: Operate OutreachPilot, the local AI cold-outreach app (find real brands, read their official site for a public email and hero product, write a personalised email with two A/B product concepts and a concept image, send from several mailboxes, track replies). Use when the user wants to start/pause outreach, check sending status or costs, add prospects by URL, set up an API key or mailbox, create a product profile to sell something new (packaging, displays, any custom product), or install/update the app.
---

# OutreachPilot

Repo: https://github.com/Alexanderhe1212/packaging-outreach. Pure Python 3.9+ standard library. One local service (`http://127.0.0.1:18800`) runs every mailbox account; the UI, the CLI and you all use the same JSON API.

## Is it installed and running?

```bash
python3 <repo>/app.py status        # accounts, today's sends, ready emails, cost
```
Not installed: `git clone https://github.com/Alexanderhe1212/packaging-outreach ~/OutreachPilot`, then `python3 ~/OutreachPilot/app.py` (macOS desktop icon: `bash scripts/install_mac_app.sh`). Not running: start it with `python3 app.py --no-browser` in the background.

## Everyday operations (prefer these; never edit the database)

| Goal | Command |
|---|---|
| Start / pause all or one account | `python3 app.py start [ACCOUNT]` / `pause [ACCOUNT]` |
| Add prospects (sites or emails) | `python3 app.py add ACCOUNT brand.com hello@other.de` |
| Token & cost report (7 days) | `python3 app.py usage` |
| Recent leads | `curl -s 'http://127.0.0.1:18800/api/leads?status=replied&limit=20'` |
| One lead incl. email + research | `curl -s http://127.0.0.1:18800/api/lead/ID` |

POST endpoints need `Content-Type: application/json`: `/api/start`, `/api/pause`, `/api/add {account, urls}`, `/api/send {id}`, `/api/skip {id}`, `/api/edit {id, subject, body}`, `/api/redo {id, what: image|all}`, `/api/settings`, `/api/test-api {connection}`, `/api/test-mail {account}`.

Read only what you need: status first, then at most ~20 leads, then a single lead. Do not dump the whole history.

## Setup the user may ask for

- **API key**: easiest in the UI (⚙ 设置 → AI 接口). Presets: OpenAI, Claude, Gemini, DeepSeek, Qwen, Kimi, GLM, OpenRouter, any OpenAI-compatible relay, local Codex CLI (no key). Each stage (discover / write / image) picks a connection + model. The image stage needs an image-capable connection (OpenAI or a relay). Never print or commit keys; they live in `<data>/secrets.json` (0600).
- **Mailbox**: ⚙ 设置 → 账号; presets for Tencent Exmail, Aliyun, NetEase, Gmail, Outlook, Zoho. Use an app password / 授权码. Then `/api/test-mail`.
- **New product to sell**: copy `profiles/packaging.json` to `<data>/profiles/<id>.json` (or ⚙ 设置 → 产品方案 → 另存为新方案), rewrite `offer`, `ideal_customers`, `concept_library`, `image.prompt`; select it on an account. `profiles/display-stands.json` is a worked example.

Data dir: macOS `~/Library/Application Support/OutreachPilot`, else `~/.outreach-pilot` (`OUTREACH_DATA` overrides).

## How the pipeline spends tokens (explain when asked about cost)

1. discover: one cheap call returns ~6 candidate domains (web search if the provider has it).
2. crawl: zero tokens — public email, hero product, price and photo come straight from the official site (Shopify products.json, JSON-LD, og tags). Sites without a public email or real product are skipped for free.
3. write: one call per lead; product photo sent at 512px low detail; static system prompt first so providers cache it.
4. image: one A/B concept image per lead using the real product photo as reference.
No review loops. Each lead's real token use and estimated cost is stored and shown in the UI.

## Rules that stay on

Only addresses published on the company's own site; one company is contacted by one account only; replies, unsubscribes, bounces and unresolved SMTP results are never emailed again; an SMTP result of "unknown" is never auto-resent; concepts are for discussion (no prices, lead times or certifications). Do not bypass these when operating the app. Sending real email is the user's decision: only start sending when they ask.
