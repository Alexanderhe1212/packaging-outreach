# Changelog

## 1.3.5 — 2026-10-19

- Separate actionable work from website cooldown waits so AI discovery can continue.
- Persist sequential recheck results, save sourced contacts, and hand off failed originals through existing sending safeguards.
- Preserve active jobs and deferred handoffs without blocking the next website.
- Reject explicit industrial machinery suppliers before automatic outreach, including prepared drafts.
- Add helper deployment for existing User Radar installations; no customer data is bundled.

## 1.3.4 — 2026-10-19

- Resolve recipient greetings from quoted evidence tied to the actual email, including corrected headings and changed addresses.
- Support HTTP 308 redirects on Python 3.9 and valid gzip pages with trailing whitespace.
- Preserve bounded retry scheduling, server retry deadlines, email rechecks and cross-account sending safeguards.
- Include Radar intake, problem tracking and the consolidated workspace accumulated since 1.3.2.

Release validation: local regression tests and public-page smoke checks. Cross-platform CI must pass before promotion. SMTP acceptance is not delivery confirmation.

## 2026-10-28 — Public customer source and Windows build kit

Publish the current runtime without private operational data. Add an embedded-runtime NSIS customer installer build, installation manual, per-user pause-on-open launcher, license notices and synthetic cross-platform CI. Preserve sending and image protections. Older image-optional/re-contact test contracts are retained under tests/legacy_v1 and not counted as passed. Windows desktop installation remains unvalidated and binaries unsigned.
