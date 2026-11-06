# Schema 13: Authoritative Conversations

Schema 13 extends the [schema 12 foundations](Schema_12.md) for Phase 3 messaging and rejects schema 12 and earlier before any DDL, without migration.

## Additional Tables

| Table | Responsibility |
| --- | --- |
| `chat_operations` | Append-only, owner-scoped command key, canonical input digest, metadata-only result, optional actual invocation reference, and committed timestamp. |
| `chat_preferences` | Independently persisted personal team/direct detail preferences without changing Agent identity fields on membership changes. |

`chat_messages.invocation_id` is nullable only for authenticated Host publications backed by a matching `chat_operations` record.

A model publication always references its actual personal invocation; ATT does not fabricate an invocation to satisfy a foreign key.

`chat_messages.reply_message_id` retains the explicit source reference, but every linked retrieval independently checks the recipient's personal view.

`chat_personal_views.read_revision_number` is a monotonic personal watermark, independent of the explicit unread override and the last successful read timestamp.

Runtime body delivery and its read watermark share one personal-window checkpoint.

The only compensation exception restores the exact prior read fields of an unreturned Host read, requires its matching preparation receipt and unchanged projection, and cannot rewrite confirmed unrelated read history or any other personal-view fields.

Reading an earlier version cannot clear a later unread revision or erase its captured reminder.

`chat_withdrawals.window_seconds` requires a finite positive value, with no fixed 600-second maximum.

Each withdrawal retains the applied window and exact last committed revision, so later configuration changes cannot invalidate historical evidence.

## Authority and Projections

Membership intervals and ordered chat events are authoritative relationship facts.

The writer derives `team_members` from the accepted open intervals after applying record deltas, rather than allowing a later progress snapshot's older member list to overwrite a relationship transaction.

Current personal message views must match the live projection; departure views must match the last authorized revision and withdrawal at their exact departure boundary.

Every publication must have all eligible recipient views, including personally hidden views, and every captured reminder preview references its exact owner's view.

Friendship requires explicit accepted consent in the current relationship generation.

Accepted older requests remain immutable historical decisions and do not grant current friendship.

Every chat operation validates its command-specific status, required metadata fields, referenced objects, acting identity, and retained business evidence, not only its JSON structure.

Edit and withdrawal receipts must reference the author's actual revision or withdrawal, personal controls must reference the actor's authorized view, and friendship receipts must match the addressed endpoint and historical request generation and outcome.

Where retained source or relationship evidence reconstructs the command input, validation recomputes its canonical digest to reject a receipt redirected to another otherwise valid object or revision.

Historical receipt validation does not substitute the current relationship or personal-control state for the state recorded by an earlier accepted operation.

Active teams' current parent-team edges must reference active teams in both transactional SQL and detached validation, independently of runtime transition reservations.

Already dissolved teams may retain parent references as historical provenance without regaining current topology authority.

The existing single-writer ownership, WAL, foreign keys, busy timeout, immutable delta versions, projection validation cache, and cancellation-safe receipts remain in effect.
