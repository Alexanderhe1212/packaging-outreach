# API / Agent protocol

The tool has no dependency on a particular agent's session or login. Keep credentials in environment variables. A single `api` block covers compatible providers; override individual stages under `providers` when capabilities differ.

| Config key | Supported kinds | Required capability |
|---|---|---|
| research | `responses`, `agent_http` | Live public web search/open, exact official source facts |
| text | `chat`, `responses`, `agent_http` | JSON output; visual input for final product identity |
| image | `image_edits`, `agent_http` | Actual product/material reference input; one base64 PNG output |

Default adapter routes:

- `chat`: `POST {base_url}/chat/completions`; JSON messages with image data URLs and `response_format: json_object`.
- `responses`: `POST {base_url}/responses`; input text/images and JSON output. Research includes `web_search` and requires a returned search-tool trace.
- `image_edits`: multipart `POST {base_url}/images/edits`; model, prompt, `n=1`, `output_format=png`, `image[]` references. Expects one `data[0].b64_json`. A gateway that exposes only `/images/generations` is insufficient for this adapter.
- `agent_http`: `POST` the exact configured `url`. Optional bearer auth from `api_key_env`.

The adapters follow the official [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [web-search guide](https://developers.openai.com/api/docs/guides/tools-web-search), and [image input guide](https://developers.openai.com/api/docs/guides/image-generation). Provider/model support must be verified with the user's own service; compatible syntax alone does not guarantee matching features.

## Custom Agent HTTP

Request:

```json
{
  "protocol": "packaging-outreach.v1",
  "stage": "research",
  "request_id": "stable-uuid",
  "instructions": "Stage-specific instruction string",
  "input": {"target": "Premium brands", "excluded_company_domains": []},
  "images": [{"mime": "image/png", "base64": "..."}]
}
```

Return `{"output": {...}}`. Stages and output contracts:

- `research`: `candidate` (object or null) and `pages`. Candidate fields: company, brand_marker, recipient, company_url, email_source_url, product_evidence_url, literal product_facts, retail_price `{amount,currency,product_url,source_quote}`, product_image_url, unit_count, count_evidence_quote. Each page has url/text. Use actual live source evidence; do not invent a success flag.
- `plan`: `a` and `b`, each `{box,insert,accessories,description,fit_reason}`. Allowed IDs are supplied in input.
- `image`: `{png_base64: "..."}`. Return one complete original noninterlaced 8-bit PNG, 128–4096 pixels per side, at most 8 MiB. Do not return a local path from the remote server.
- `draft`: `{subject,body,identity:{correct_product,correct_count,usable_image}}`, with literal boolean identity values. The app supplies real product and concept images.

Request IDs are stable across recovery. Respect the `Idempotency-Key` header where supported. No blind retry on timeouts or malformed/ambiguous output. HTTP 429 requeues after backoff; it must mean the request was refused before work. A provider that returns asynchronous jobs must implement a bridge that waits for a bound final result or explicitly surfaces uncertainty; this tool does not guess vendor-specific polling URLs.

API credentials are never sent to redirected hosts: the client does not follow API redirects. HTTPS is required except loopback HTTP for local models/agents.

## Public references

`source_mode: direct_https` uses pinned public HTTPS fetches for exact official evidence. Private, loopback and link-local source addresses are rejected. Model APIs are separate explicitly configured endpoints and may be local.

For JavaScript sites, a trusted web-enabled Agent can be configured with `source_mode: browser_excerpts`. Those hashes cover excerpts, not original HTTP pages; this mode deliberately trusts the chosen research provider's collection. Product image URLs still must appear in its source evidence.
# Stage-specific speed settings (v0.2)

For v0.3 economy mode, `providers.vision` handles the new `identity` API stage; `plan` returns the normal A/B plan plus `email` slots. The pipeline's durable job stages are unchanged. See [economy](economy.md). Chat providers accept `json_mode: prompt` to omit `response_format`, and `token_limit_parameter: max_tokens` for older compatible services. Text-only requests now use a plain string content; vision requests always retain their image inputs. No vendor/version names are inferred as capabilities.

`providers.plan` and `providers.draft` optionally override the shared `providers.text` adapter. Plan can use a fast text model; draft requires vision. `max_output_tokens` and `reasoning_effort` are sent only when configured, using each endpoint's field names. `providers.image` optionally accepts `quality`, `size`, and model-supported `input_fidelity`. The PNG/reference-input contract is unchanged.

`provider_concurrency` limits concurrent calls **across all accounts** in a workspace; `concurrency` controls per-account stages. Neither increases the API vendor's quota. See [performance](performance.md).

Stage payloads now include `seller_profile`. Plan output uses `structure`/`support`; legacy `box`/`insert` output remains accepted. Research receives `price_policy`, `seller_offer`, excluded domains and excluded recipients. When the profile does not require price, `retail_price` may be null. The agent must still provide real website/email/product/image evidence.
