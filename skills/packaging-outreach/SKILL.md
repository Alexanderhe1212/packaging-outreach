---
name: packaging-outreach
description: Run personalized premium packaging outreach with real public brand research, varied A/B box concepts, value emails, resumable API stages, and SMTP/IMAP records. Use when the user asks to prospect packaging buyers, create individualized packaging proposals, run GUKA/MTT or other independent brand profiles, move the workflow between agents, or connect model/agent APIs.
---

# Packaging Outreach

Use the standalone tool at https://github.com/Alexanderhe1212/packaging-outreach. Read [runtime.md](references/runtime.md) for commands and provider setup. Read [workflow.md](references/workflow.md) for packaging and message constraints. No vendor-specific CLI or browser account is required.

## Start with the user's existing authorization and state

1. Locate the explicitly supplied workspace/config. Do not guess Desktop paths or overwrite an existing project. Keep separate sender profiles and preserve existing databases, held jobs, logs, replies, opt-outs and uncertain submissions.
2. Run `python3 -m packaging_outreach --config CONFIG status` and `doctor`. Report actual missing API capabilities or configuration. Never print, copy into files, or commit API/email passwords; use the configured environment variable names.
3. Use existing setup and authorization. Do not introduce per-email approval. Public publication requires an explicit instruction; ordinary outreach authorization does not publish customer records or private packaging references.
4. Start or pause through the tool. The service process must remain running for continuous work. Do not promise future execution from a chat that has no running service.

## Carry out the whole flow

- Research one real, suitable brand using a live web-capable provider; record official company/contact/product URLs, exact published business email, real SKU, count and source facts. Never guess an email, claim purchase intent without evidence, or call product existence a buyer pain.
- Prefer appropriate premium perfume, jewelry and suitable consumer brands. Apply the configured target; the current source parser handles official USD/EUR 100+ SKUs, not guessed foreign exchange conversions.
- Use the user's private material manifest and recent structure history. Choose two different suitable opening structures and fitted inserts. Use ribbon, handle, tissue or filler only where useful. Keep closures, anchors and product support coherent. Treat concepts as proposals, not approved engineering.
- Keep one authentic product-bound A/B image. Use actual reference image inputs. Do not substitute a blank fixture, unrelated image, old customer's image, or text-only imagined product.
- Write concise factual option-A and option-B value. Let the application insert the single AB image, two correct WhatsApp links, brand signature and opt-out in that order. Never mix sender identities.
- Use automatic staged execution after initial configuration. Preserve pipeline concurrency and caches. Do not add repeated subjective image scoring or automatic redraw loops.
- Before enabling a new sender, run the specifically requested own-account text/image mailbox test. Require SMTP final acceptance and IMAP MIME image hash match. If the test is waiting for receipt, use `verify-mailbox-test`; do not send another test automatically.

## Report and recover accurately

Read actual job/attempt records. Distinguish prepared/spooled, SMTP accepted, actual IMAP receipt, replies, and unknown. A reachable UI or an online service is not a sent email.

Keep request IDs and Message-IDs automatic. Let completed API checkpoints resume without a new call. If an API call or SMTP DATA outcome is unknown, retain the uncertainty and continue other customers; do not delete records or retry blindly. Read [operations.md](references/operations.md) before recovery or new follow-ups.

When the user explicitly requests a new valuable follow-up, locate the accepted same-brand attempt internally and use the follow-up command with the new concrete value. Do not require a manual customer-ID spreadsheet. Ordinary prior Sent is not a permanent ban on such follow-ups; opt-outs, explicit refusals and unresolved unknown still matter.

## Portable handoff

Give another agent the GitHub URL, this Skill, and the local config path. The receiving agent uses the same CLI/JSON protocol. It must supply actual research, vision and reference-image-generation capabilities; an ordinary text-only API cannot perform them by declaration. Keep private business preferences outside the public repository.
