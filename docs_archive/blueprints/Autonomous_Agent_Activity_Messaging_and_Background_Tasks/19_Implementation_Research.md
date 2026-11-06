# 19. Implementation Research Boundaries

[Back to blueprint index](README.md).

The confirmed behavior above is the input to implementation research rather than a list of institutional decisions to reopen.

The following groups identify engineering contracts to work out without silently changing those agreements.

For current decisions and remaining engineering dependencies, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/19_Decision_Status.md).

## A. Personal Activity and Wake Semantics

Define how a person continues working, deliberately waits, temporarily stops, receives pending information, and becomes active again without rounds or parallel copies.

Preserve the confirmed default that new messages notify an active person at a safe boundary and activate an idle person unless an explicit admitted temporary do-not-disturb preference or sleep plan defers the activation.

Not speaking imposes no restriction on other activity, and the AI may voluntarily sleep, set wake conditions, and use temporary do-not-disturb preferences.

These permissions do not prescribe an automatic endless model-call loop or establish a specific tool API.

Waiting on one background execution must not require the whole person to become unavailable for unrelated messages or activities.

Finalize condition matching, temporary preference expiry, timer persistence, and safe activation admission while retaining the finite latest-wake safeguard and non-suppressible important notices.

Keep offline time out of restored sleep countdowns rather than applying absolute wall-clock catch-up.

## B. Conversation and Read-State Contracts

Finalize team-stream and direct-chat APIs, explicit publication, per-person read markers, preview budgets, and message storage.

Implement tool reads as read-state updates, permit explicit read and unread changes, and keep previews independent of read state.

Enforce the union of membership intervals for chat history, including departures, rejoining, counts, search, and quoted references.

Do not interpret message-read state or absence of a reply as a governance vote or permission to act for another person.

## C. Friendship State and Allowance Rules

Implement bilateral friendship with individually controlled block decisions and refusal handling.

Either block prevents both directions, breaks friendship, and generates a relationship notice, while both cleared blocks return the pair to stranger contact with a fresh allowance.

Finalize atomic allowance accounting, request deduplication, and stale-request handling without restoring an old friendship implicitly or granting new allowances through ordinary request retries.

## D. Background Execution Contracts

Finalize safe detachment, threshold measurement, explicit background creation, execution handles, cancellation, results, health signals, and resource admission.

Preserve the confirmed default of 120 seconds, eligibility of non-self-modifying operations, and explicit eligibility of Private DocLib writes without equating detachment with cancellation or restarting the execution.

## E. Existing Work Artifacts

Reuse existing personal and team DocLib operations for work artifacts rather than introducing WorkItem APIs or a mandatory completion procedure.

Preserve AI-authored meaning and business judgments independently of execution state, technical labels, and health assessment.

## F. Health Supervision in an Event-Driven Runtime

Finalize permitted observations, privacy boundaries, triggers, and interventions for detecting actual unhealthy behavior without supervising business progress.

## G. Persistence and Recovery

Finalize per-operation commit and recovery boundaries after the activity, communication, and executor contracts are sufficiently clear.

Implement durable activity markers, consistent personal-context checkpoints, recovery annotations, protected recovery notices, and the confirmed activation matrix.

Do not automatically poll, reconnect, or replay external execution, and do not promise arbitrary coroutine continuation or safe replay of unknown side effects.
