# macOS installation and recovery

## Clean installation

Use Python 3.10 or newer. Download or clone this repository into `~/Outsearch Pilot`; quote the path because it contains a space. Do not import historical databases for a clean installation.

```sh
cd "$HOME/Outsearch Pilot"
OUTREACH_PYTHON="$(command -v python3)" bash scripts/install_mac_app.sh
```

The installer copies code into `~/Library/Application Support/OutreachPilot/app`, creates `~/Desktop/Outsearch Pilot.app`, installs the `~/.local/bin/outreach` command and the bundled Codex/Claude skill. It requires an existing Python installation and does not create credentials. Previous launchers are retained under `~/Library/Application Support/OutreachPilot Backups/launchers`, away from the Desktop.

Double-click **Outsearch Pilot** to open the local application without Terminal. Repeated opens reuse the same backend. Opening the application does not unpause accounts or enable automatic sending. Use the settings screen to enter credentials privately and test each mailbox and AI connection. Review automatic sending, follow-ups and mailbox cleanup before starting accounts. Keep MTT and GUKA identities and signatures separate. For reviewed sending, leave automatic sending off and approve each draft explicitly.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 app.py status
```

Tests use temporary data, mock AI/product services and fake mail transport. They do not send customer email. Validate a real Finder double-click and repeated double-click, a responsive local UI, one backend process, and unchanged account run/send settings. Logs live in the data directory (`app.log`, `launcher.log`). SMTP acceptance is not proof of inbox delivery.

## Private backup and recovery

The runtime data directory contains settings, credentials, SQLite databases, customer records, suppression lists, images and email archives. Keep it private; never commit it or a full local backup to GitHub. Before repair, pause all accounts, wait for in-flight preparation and sends to finish, then quit the service. Make a private copy of code and data outside the Desktop with directory permissions 700. Copy a SQLite database only while stopped, or use SQLite's backup API; do not copy a live database file without its WAL.

Recover code by first saving the current code separately, then restoring the selected known-good source and reinstalling the launcher. Do not replace current customer data with an older snapshot: that loses subsequent sent/replied/unsubscribed records and can cause duplicate outreach. Preserve the newest suppression and sending history. Database recovery requires explicit selection and reconciliation of those records. A `sending` attempt interrupted by restart is changed to `unknown` and must not be automatically resent. Reconcile it against the mailbox before any manual decision.

If an older Desktop `.command` or duplicate app exists, first verify the new app, then move only the confirmed obsolete launcher to Trash. Do not empty Trash or move the source folder. Fresh installation never requires restoring old data.
