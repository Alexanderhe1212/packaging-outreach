---
name: packaging-outreach
description: Run product-configurable trade outreach with real public customer research, tailored A/B concepts, personalized emails, measured multi-account performance, and resumable delivery. Use for premium packaging or other configurable physical products, GUKA/MTT or independent sender profiles, five-minute workflow optimization, agent handoff, and model/agent API setup.
---

# Packaging Outreach

Use https://github.com/Alexanderhe1212/packaging-outreach with the user's existing configuration and authorization. No per-email approval or manual customer-ID spreadsheet.

## Normal flow

1. Read current status and at most 25 recent records. Open only the selected customer's details/image. Older records are paginated; do not reload the full history or all references.
2. Find one suitable real business, its official product and exact public business email in one research pass. Give the model small index hints; check the selected domain/contact against the complete local index. Keep a few supported product facts and drop unsupported extra prose. No invented contact, purchase intent or pain.
3. Use the actual product image in one A/B planning-and-email call. Choose packaging by the product, not retail price. A/B can mix structures. Carton options retain 1,000-piece MOQ. Use only relevant material references; fit matters more than novelty. Fold soft goods plausibly and preserve brand/SKU identity.
4. Generate one product-bound A/B image. Perform one brief factual identity check; no subjective scoring loops or automatic redraws. Write a greeting, a concrete benefit for A/B and one easy reply invitation. The app adds the image, two sender-correct WhatsApp links, signature and opt-out.
5. Send through the configured single final gate, record the result, and continue to the next customer. Keep source/image/SMTP uncertainty local to that task. Never blindly repeat unknown image calls or SMTP submissions; retain opt-outs, refusals and sender separation. SMTP acceptance is not proof of receipt.

## Read only when needed

- Commands, provider configuration or a new sender: [runtime](references/runtime.md). New sender setup needs the specifically authorized mailbox test; normal operation does not repeat setup checks.
- Product catalogue or message details: [workflow](references/workflow.md).
- Smaller models and useful sales copy: [economy](references/economy.md).
- A measured speed bottleneck or another product profile: [products and speed](references/products-and-speed.md).
- Failure, unknown delivery or an explicitly requested valuable follow-up: [operations](references/operations.md). Inspect the one affected request; do not clear history or restart unrelated tasks.

Continuous operation requires the running service. Use recorded stage timings; five minutes is a target, not a claimed result or a cancellation timer. Keep secrets, customer data and private material files outside Git; publish code only when authorized. Concepts require sample validation, never claim engineering approval.
