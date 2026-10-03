# Recovery and follow-up

- `spooled`: prepared `.eml`, no SMTP call.
- `accepted`: final SMTP 250 recorded, not proof of client receipt/read.
- `unknown`: remote outcome uncertain. Preserve records and reconcile using the original API request ID or Message-ID.
- `blocked`: source, configuration, factual identity or recipient issue; other customers continue.

The workspace has one SQLite worker lease and durable API/stage claims. On abnormal restart, interrupted jobs/runs and submissions are classified conservatively as unknown. A successful cached call is reusable; an unresolved remote call is not a reason for a fresh image call. There is currently no automatic provider-specific remote-task reconciliation endpoint: investigate the recorded request and import only a verified result using a reviewed recovery operation. Do not manipulate the database to pretend success.

Preserve unsubscribe, explicit refusal, ordinary replies and hard SMTP recipient rejection. Reply handling requires a conversation decision, not an automatic fresh cold email.

For a user-authorized meaningful follow-up, find the accepted same-brand attempt in status and pass it to `enqueue --followup-of ID --reason 'Concrete new value' --brand BRAND candidate.json`. Source evidence is checked again. Cross-brand first-contact duplicates and unresolved unknown cannot be bypassed by changing the recipient, clearing Sent history, or regenerating Message-ID.

Use one shared workspace for multiple brand profiles so company ownership is shared. Independent workspaces do not automatically share suppression history; import required constraints deliberately before outreach.
