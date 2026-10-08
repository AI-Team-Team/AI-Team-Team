# 9. Direct Personal Chat and Friendship

[Back to plan index](README.md).

## 9.1 Relationship records

Use a canonical pair identity with independently owned block and refusal controls, bilateral friendship state, relationship-generation evidence, and directional stranger accounting.

Keep friendship requests and their responses separately attributable rather than treat any direct message as consent.

Root is an ordinary Agent endpoint for these records.

Requests and messages targeting inactive, deleted, or audit-scoped identities must fail closed according to the finalized lifecycle policy.

## 9.2 Admission transaction

1. Resolve the sender from the current personal invocation and validate both identity references.
2. Lock the pair's relationship admission and capture its current generation.
3. Reject delivery if either block is set or the recipient's applicable refusal restriction remains active.
4. Resolve an existing idempotency record before charging stranger allowance again.
5. If the pair is not friends, enforce the confirmed three-message allowance using the selected directional accounting rule.
6. Commit the source message, allowance update, and recipient notification in one transaction.
7. Return acceptance only after that transaction succeeds, then admit the same recipient's personal activity as allowed by sleep and do-not-disturb.

Failed transactions do not consume allowance, and repeated submission of the same admitted operation does not create another message.

An explicitly new message with identical text is still a distinct message rather than body-based deduplication.

## 9.3 Relationship transitions

- Accepting an eligible current request establishes friendship without granting any team, DocLib, inbox, or execution authority.
- Either block ends existing friendship and prevents direct sends in both directions.
- A system relationship notice records blocking without using direct chat to bypass the block.
- Clearing one block leaves the other person's block effective.
- Clearing the final block starts a new stranger-contact generation with a fresh allowance and no restored friendship.
- Removing an established friendship starts a new stranger-contact generation under the agreed reset rule.
- Removing a nonexistent friendship, withdrawing a request, or resubmitting an unaccepted request does not reset allowance.
- Decisions about older requests cannot restore friendship across a relationship-generation change.
- Messages and previously legitimate personal memories are not erased by a relationship change.

The confirmed D06 contract is three messages per sender per relationship period, metadata-only friendship requests initially, and an explicit recipient-owned operation to lift refusal.

Crossed requests remain requests until an explicit acceptance is recorded rather than infer friendship from two expressions of interest.
