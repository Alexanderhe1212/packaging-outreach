# Changelog

## 1.3.4 — 2026-10-19

- Resolve recipient greetings from quoted evidence tied to the actual email, including corrected headings and changed addresses.
- Support HTTP 308 redirects on Python 3.9 and valid gzip pages with trailing whitespace.
- Preserve bounded retry scheduling, server retry deadlines, email rechecks and cross-account sending safeguards.
- Include Radar intake, problem tracking and the consolidated workspace accumulated since 1.3.2.

Release validation: local regression tests and public-page smoke checks. Cross-platform CI must pass before promotion. SMTP acceptance is not delivery confirmation.
