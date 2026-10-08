# 13. Authoritative Transactions and Concurrency

[Back to plan index](README.md).

## 13.1 Commit and dispatch separation

An authoritative domain transaction captures immutable versioned records, awaits its exact commit receipt, and only then publishes callbacks or schedules model activity.

Creating a notification inside a staged transaction must not dispatch it before the source transaction succeeds.

Idempotency records cover the committed source operation and are not inferred from callback delivery.

Cancellation after a transaction is accepted waits for its known commit or rollback before releasing the domain's mutation protection.

An accepted operation remains queryable by identity even if its caller loses the response after successful commit.

## 13.2 Lock responsibilities

| Protection | Scope | Forbidden wait while held |
| --- | --- | --- |
| Runtime or publication gate | Admission, restore eligibility, generation changes, and registry publication. | Arbitrary LLM or tool execution. |
| Personal invocation guard | The same person's model activity and Working Context mutation. | Another required invocation of that same person. |
| Short activity admission lock | Ready ownership, arrival generation, and intent transitions. | External execution or model generation. |
| Team relationship lock | Membership, shared publication or revision ordering, withdrawals, and departure-view freezing. | Member model activity or business conversation completion. |
| Relationship pair lock | Friendship, blocks, refusal, stranger accounting, and direct-message admission. | Model activity or sender reply. |
| Domain decision lock | Case validation, ballot acceptance, and authoritative outcome transition. | Governance voters' model activity. |
| Resource and library protections | Cross-owner conflicting access, atomic file publication, moves spanning source and target, and multi-library operations in stable order. | Another person's model judgment. |

Define one documented acquisition order for transactions spanning these protections and use captured versions with commit-time revalidation when a long wait would otherwise be required.

No synchronous thread lock is held across an `await` that requires another participant to make progress.

Short synchronous publication locks remain useful for worker-thread discovery and callback inspection of registry snapshots.

Detached executors do not inherit the personal invocation guard as an indefinitely retained resource.

Keep cycle detection for remaining genuinely synchronous host dependencies rather than removing safety checks because ordinary delegation no longer waits.

## 13.3 Backpressure and observers

Bound live model and executor admission without discarding already accepted records.

Coalesce ready scheduling by owner and notifications by their explicit factual deduplication identities.

Separate queue capacity, model budget, and executor limits from personal choice to continue or become idle.

Callbacks remain ordered synchronous or asynchronous observers whose failures cannot invalidate committed source records.

Callback payloads contain allowed IDs, scopes, transition facts, and results without private bodies or sensitive arguments.
