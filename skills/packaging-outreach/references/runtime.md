# Runtime

Clone https://github.com/Alexanderhe1212/packaging-outreach and work from that directory, or install the Python package. All commands accept `--config PATH` before the subcommand.

```bash
python3 -m packaging_outreach init ../my-outreach
python3 -m packaging_outreach --config ../my-outreach/outreach.json doctor
python3 -m packaging_outreach --config ../my-outreach/outreach.json serve
```

Configure `api.base_url`, `api.text_model`, `api.image_model`; provide the API key in `OUTREACH_API_KEY`. Set brand sender, international WhatsApp digits and signature. `providers` can override research/text/image individually with an `agent_http` endpoint implementing the documented JSON protocol.

The default research uses Responses with real `web_search`; text uses OpenAI-compatible Chat Completions with image inputs; image uses reference-image `images/edits` multipart. Third-party services may support only a subset. Check capabilities rather than silently dropping reference images or fabricating search.

`serve` binds loopback only and offers start/pause/status. CLI equivalents: `start`, `pause`, `run`, `status`. `run --until-idle` handles existing queued work without unlimited discovery. `start` saves running state; it does not create a background process by itself.

`auto_send: false` exports emails. To send, configure TLS SMTP/IMAP plus a password environment reference, complete `mailbox-test --brand BRAND --image PNG`, then set `auto_send: true` and restart. The test is sent only to that profile's own sender address. API keys do not include mailbox credentials.

For imported research use `enqueue --brand BRAND candidate.json`; it validates source evidence before entering concept generation. Run `sync --brand BRAND` to ingest known-contact replies. CLI JSON output can be consumed by any agent. HTTP `/status`, `/start`, `/pause` support local orchestration with a matching Host and JSON Content-Type.
