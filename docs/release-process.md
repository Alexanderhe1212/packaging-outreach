# Release process

Every validated release increments `outreach.VERSION`, updates CHANGELOG.md and includes regression tests. Use a review branch and require the Linux/macOS/Windows Python 3.9/3.12 matrix before merging to main. The in-app update check reads the main-branch version.

Publish source only. Never include runtime databases, account settings, credentials, email history, customer captures or local backups. Preserve user data during installation and restart only after active work finishes. A GitHub source release does not host the local backend.

## User Radar helper update

The repository includes `radar_automation` helpers for the existing local User Radar installation. It does not bundle its crawler dependencies or private research data. Update with `python scripts/install-radar-automation.py --radar-dir PATH_TO_EXISTING_RADAR`, then gracefully restart its automatic worker after active work has finished. The queue defaults to the established local maintenance file; `USER_RADAR_RECHECK_QUEUE` overrides its location. Do not create a second worker: the existing automatic worker holds a singleton lock.

Recheck states distinguish source query completion, saved contacts, actual handoff, protected records and required review. A saved contact or queue handoff is not SMTP acceptance or delivery.
