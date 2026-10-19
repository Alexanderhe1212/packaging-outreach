# Release process

Every validated release increments `outreach.VERSION`, updates CHANGELOG.md and includes regression tests. Use a review branch and require the Linux/macOS/Windows Python 3.9/3.12 matrix before merging to main. The in-app update check reads the main-branch version.

Publish source only. Never include runtime databases, account settings, credentials, email history, customer captures or local backups. Preserve user data during installation and restart only after active work finishes. A GitHub source release does not host the local backend.
