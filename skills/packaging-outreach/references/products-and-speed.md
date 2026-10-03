# Products and speed

Choose the configured `product_profile`. Default `premium-packaging` supplies box structures, inserts, accessories and a USD/EUR100+ source filter. Other profiles in `product_profiles` define offer, target, structures, supports, accessories, design_rules, validation_note, price_policy and optional private material_manifest. See the repository's `examples/retail-displays.json` and `docs/product-profiles.md`. Keep unknown engineering data unknown.

For two accounts, use distinct brand/sender/WhatsApp/signature/mail settings in one workspace. Discovery rotates accounts, and the company is claimed before concept work. Different commercial customers require separate workspaces and private reference/credential directories; the local UI is not a multi-tenant hosted service.

Use `python3 -m packaging_outreach --config CONFIG metrics` (or status/UI) to inspect accepted_end_to_end, prepared_end_to_end, accepted_interval, stage/API p50/p95 and held jobs. End-to-end begins when research is enqueued, not after the effect image is done. No samples means unverified speed.

A five-minute budget may allocate 90s research, 20s plan/reference download, 150s image, 25s draft/identity and 15s send. These are planning targets, not measured promises. Do not convert them to hard cancellation/retry timers. Focus on the measured slowest stage.

The tool caches official pages briefly and actual reference images persistently, overlaps plan and reference download, prioritizes ready mail, and limits shared provider concurrency. `providers.plan`/`draft` can override text; image quality/size are optional supported-service controls. Never secretly change a paid service, discard real image references, or mark an unverified recipient/product as verified to meet a speed goal.
