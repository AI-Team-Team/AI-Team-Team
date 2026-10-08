# 10. Background Execution Has Two Entry Paths

[Back to blueprint index](README.md).

## Confirmed Direction

An AI can deliberately initiate execution as a background task.

A tool that has not finished after two minutes becomes background execution, with that default duration configurable.

The default automatic-detachment threshold is 120 seconds.

```text
Explicit background execution ──┐
                               ├──> BackgroundTask
Automatic detachment ───────────┘
```

Automatic detachment changes how the owner waits for the execution rather than restarting the operation.

Explicit creation and automatic detachment use the same task-record, query, notification, and management mechanism rather than unrelated background systems.

It is not itself a failure, cancellation, retry, deadline expiry, or new execution attempt.

The AI receives a task reference and can handle other matters while the same execution continues.

A later completion becomes a task result and a personal notification rather than an extra tool result inserted into an already completed native tool-call sequence.

## Ownership and Description

A personal background task belongs to the Agent and is not automatically transferred, reset, or cancelled when that Agent joins or leaves a team.

The AI may give the task a description and labels to make later queries useful.

If an execution was authorized under a particular team context, that original scope must remain identifiable rather than silently changing to whichever team the owner uses next.

Continuing identity and continuing execution do not imply that revoked file permissions remain usable.

Sharing a personal task with a team and creating a team-owned task require additional rules that have not been finalized.

For current execution ownership and sharing boundaries, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Tasks.md).

## Eligible Background Operations and Safe Execution

Operations other than those modifying the AI itself are eligible for background execution.

Changes to personal identity, personal instructions, model binding, Working Context, or lifecycle must stay coordinated with that person's serial model activity rather than becoming a second independently mutating self.

Writing the person's Private DocLib is explicitly eligible for background execution because it creates work artifacts rather than replacing the individual.

Private file ownership, archive protection, path validation, library locking, and permission checks still apply.

Any resulting observation or memory update returns through the owner's serial activity mechanism rather than letting the background worker rewrite personal model context concurrently.

Arbitrary Python coroutines, subprocesses, and provider requests do not all have the same safe-detachment behavior.

An operation may hold a personal invocation lock, a transaction, or scope-sensitive mutable state that cannot simply be abandoned while it continues running.

The implementation must not satisfy the two-minute rule by launching a second copy or releasing synchronization while the original operation can still mutate the same personal state.

The executor and tool contracts must preserve complete authoritative commits, atomic file operations, rollback, and safe lifetime management even when the owner stops synchronously waiting.

Background eligibility is not permission to interrupt a transaction halfway through or retain unsafe references into a replaced manager state.

The implementation needs an explicit way to describe and enforce self-modifying behavior for built-in and host-provided tools rather than claiming that arbitrary Python callables can be proved safe by inspection.

## Open Choices

For current detachment, timing, and executor contracts, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Tasks.md).

- How eligible operations detach without violating commit boundaries or concurrent ownership, and how excluded self-modifying operations handle a long wait.
- Whether the threshold includes queueing, authorization, auditing, execution retries, or only actual execution time.
- How explicit background creation identifies a tool or external execution without bypassing ordinary validation and authorization.
- How tool batches behave when one member detaches and another returns immediately.
- Which locks and state references an execution may retain after detachment.
- Cancellation ownership, cancellation acknowledgement, and handling of results racing with cancellation.
- Admission control and resource limits without confusing a resource rejection with an Agent's decision to stop working.
