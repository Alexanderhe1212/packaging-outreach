# Operations and private state

Run one `serve` or `run` process per configured workspace. A durable worker lease prevents a second worker taking over while heartbeats are fresh. All brand profiles in that workspace share company first-contact and stop records. Use separate profiles, never change one sender into another.

The engine overlaps one research task, two concepts, one draft and one send per brand by default. `concurrency` controls these capacities. More parallel work is not always faster: respect the configured API's actual rate limits. The tool does not promise a fixed sends-per-hour figure.

Only the newly generated runtime directory stores database, image/API checkpoints, message identifiers and exported mail. Keep it out of Git. SQLite uses WAL and closes connections explicitly. No legacy CRM or credentials are imported implicitly.

## Controls

`start`/`pause` persist scheduling state; `serve`/`run` are the process that executes work. Pause stops new tasks while already submitted operations finish. A live mailbox send is not interrupted mid-DATA just to make a UI look stopped. On Ctrl-C the scheduler drains current futures while maintaining its lease.

`auto_send` defaults false. After filling the mail profile, run a self-addressed real-image `mailbox-test`, then `verify-mailbox-test` if actual receipt is delayed. The latter only reads the original test; it does not resend. Successful proof is bound to sender and SMTP/IMAP endpoints. Enable auto_send and restart after it passes.

IMAP uses read-only selection and BODY.PEEK. It examines mail from known outreach contacts, up to the latest 30 matching messages per recipient. It captures explicit opt-out/refusal and related replies. This is a minimal correspondence ledger, not a full inbound CRM or universal bounce parser.

## Uncertain outcomes

`spooled` means no SMTP call. `accepted` requires final SMTP 250. `unknown` may mean the remote side completed before the connection failed. Absence from a recent inbox view is not evidence that an email was never submitted.

API runs retain deterministic request IDs and checkpoints. Successful plan/image calls are not repeated when the next stage resumes. On a process crash, interrupted running work is held as unknown rather than generated/sent again. Version 0.1.0 does not implement every provider's remote job lookup: reconcile its recorded request ID before recovering a result. Do not remove a started record to force a retry.

Completed emails retain Message-ID, raw MIME hash, trace stages and response result. Opt-outs, refusal, unknown and ordinary reply handling remain separate. A user-authorized valuable follow-up can reference a same-brand accepted attempt via `enqueue --followup-of ID --reason TEXT`; changing recipients or sender brands is not a follow-up authorization.

## Testing and supported scope

The test suite uses synthetic brands, in-memory/mocked SMTP and local HTTP fixtures. No customer records, actual API keys, mailbox passwords, private PDF pages or live generated images are part of the repository. Real provider compatibility and delivery depend on the API/mail account configured later by the operator.

Targets currently require same-host official company/contact/SKU evidence and USD/EUR 100+ pricing. Company matching normalizes the hostname, not a full corporate-parent graph. Image references support the official site or Shopify CDN. Extend these policies deliberately for other verified cases.
