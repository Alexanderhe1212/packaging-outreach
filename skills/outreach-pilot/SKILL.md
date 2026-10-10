---
name: outreach-pilot
description: 一键开发客户 / AI 外贸开发信（OutreachPilot）。Use whenever the user says 开工, 收工, 开发客户, 找客户, 发开发信, 开发信状态, 看回复, 加客户, "start outreach", "check outreach", or asks about MTT/GUKA cold emails, sending status, replies, costs, API/Codex setup, or selling a new product with the outreach app.
---

# OutreachPilot — one command

The app does all the work (find brands → read official site → write email + A/B concept → concept image → send → track replies). Your job is only to call it. Do not research customers, write emails or edit its database yourself.

## The commands (that is the whole interface)

| User says | Run |
|---|---|
| 开工 / 开始开发客户 / start | `outreach go` |
| 收工 / 暂停 / stop | `outreach stop` |
| 状态 / 今天发了多少 / status | `outreach status` |
| 看回复 / 有人回复吗 | `outreach replies` |
| 加客户 brand.com … | `outreach add ACCOUNT brand.com other.co.uk hello@x.de` (accounts: see `outreach status`) |
| 打开界面 | `outreach open` |
| 花了多少 token / 费用 | `outreach usage` |

`outreach go` starts the background service by itself if needed, starts every account and prints the status — then report that status to the user in 2–4 short lines (per account: running/paused, sent today, ready, replies, any ⚠ error) and stop. One command, one short answer.

If `outreach` is not found: `python3 "<repo>/app.py" go` (same commands). If it still fails because localhost/network or starting a background process is blocked by your sandbox, rerun the same command with the permission/escalation your environment offers; do not try to work around the app.

## When status shows an error

- `等待设置` / no API key, or `API 鉴权或额度问题` → the user picks an AI connection in the UI (`outreach open` → ⚙ 设置 → AI 接口). Without an API key choose 「本机 Codex」 for all three stages (uses the ChatGPT subscription). Never ask the user to paste keys into chat.
- `Codex 调用失败 … login` → the user runs `codex login` once.
- `邮箱登录失败` → fix the mailbox 授权码 in ⚙ 设置 → 账号.
- `⚠ 旧版开发信程序仍在运行` → tell the user; old programs must be closed to avoid double sending.

## Selling something new

Copy `<repo>/profiles/packaging.json` into the UI's ⚙ 设置 → 产品方案 → 另存为新方案, rewrite offer / ideal customers / concept library / image prompt, select it on an account, then `outreach go`.

## Rules that stay on

Only emails published on the company's own site; each company is contacted by one account only; replies, unsubscribes, bounces and unknown SMTP results are never emailed again. Sending real email is the user's call: run `outreach go` only when they ask to start.

Details (JSON API for other tools): POST `http://127.0.0.1:18800/api/{start,pause,add,send,skip,edit,redo}` with `Content-Type: application/json`; GET `/api/state`, `/api/leads?status=replied&limit=20`, `/api/lead/ID`, `/api/usage`.
