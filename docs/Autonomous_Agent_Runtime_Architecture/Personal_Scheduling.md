# Personal Scheduling and Continuation

ATT admits model-driven activity by stable Agent identity rather than by team membership or discussion round.

## One Owner

An Agent has one coordinated personal activity, one bounded invocation at a time, one Working Context, and continuous owned memory across memberships.

Registration is inert until authoritative admission and runtime bindings are ready.

`activate_agent()` returns a new `QUEUED` admission or a `COALESCED` reference to the existing owner admission.

Coalescing does not replace a busy person's captured scope or start another invocation.

Different eligible people may progress independently even when they share an AgentTeam or one member remains silent.

## Admission and Fairness

The manager deduplicates ready work by owner and uses bounded activity/model capacity.

The personal invocation guard coordinates the same person's model requests and context mutation.

Per-invocation request and tool-batch budgets create accepted checkpoints and fair queue yields.

They preserve continuing intent and do not require another arrival to restart work or another member's answer to make progress.

Capacity, tool availability, model availability, and the person's explicit intent remain independently observable.

Accepted sources survive backpressure rather than depend on a successful callback or an unbounded Task per membership.

## Current Invocation Surface

The manager exposes separate admission, inspection, checkpoint, and answer-observation methods over this scheduler.

| Host operation | Returned fact |
| --- | --- |
| `await activate_agent(agent_id, scope=...)` | A new or coalesced `ActivityAdmission`, without waiting for an answer. |
| `inspect_agent_activity(agent_id)` | An `ActivityView` of current intent, availability, admission, and scope. |
| `await wait_for_activity_checkpoint(admission_id, intent=...)` | An accepted personal boundary, optionally filtered by intent. |
| `await execute_agent_interaction(agent, prompt, team=...)` | An `InteractionResult` observing the same person's answer or explicit stopping boundary. |

The [public API reference](../user/API_Reference.md#-attmanager) defines full signatures and observer-cancellation behavior.

Technical budgets bound one invocation and supply no whole-team completion or synchronization contract.

## Explicit Controls

Activity continues by default without a required `continuing` tool declaration.

`set_activity_intent` accepts deliberate idle or finite sleep, while `set_operation_scope` requests the next authorized scope.

An ordinary answer, silent reading, tool use, or artifact writing supplies no implicit stop, shared publication, or business-completion result.

A Native batch allows at most one intent control and one scope control, with duplicate or contradictory controls rejected before their effects.

Controls apply only after every issued call has a complete observation or valid background handle and the checkpoint transaction succeeds.

A rejected stop checkpoint withdraws staged control state without erasing factual observations.

An observer cancelled after a successful stop receipt cannot reopen the completed admission.

## Addressed Interaction and Observation

`execute_agent_interaction()` submits a personal instruction and observes an actual answer or explicit stopping boundary through the same runtime.

Its `InteractionResult` contains the real invocation and team provenance.

Tool-only responses, fairness checkpoints, and scope changes alone do not satisfy an answer observer.

An instruction not yet presented when the person chooses idle or sleep remains observable through a subsequent admission.

Cancellation before instruction acceptance leaves no partial source or admission, while cancellation after acceptance cannot discard the accepted source or its scheduling handoff.

Cancelling an observer does not cancel another person's already dispatched model request.

Genuine synchronous dependencies reserve identity edges and reject self-dependencies and cycles of any length.

A person waiting for another person's answer yields its activity-capacity slot and rejoins the same FIFO capacity gate, allowing acyclic dependencies to progress with one available slot.

Observer cancellation releases its dependency reservation without waiting for or cancelling the downstream personal activity.

Close and state replacement explicitly release observers whose response can no longer arrive from that runtime generation.

## Failure Boundaries

Malformed tool arguments, unknown tools, missing files, permissions, and business refusals are classified observations that leave personal activity available for correction or another choice.

Eligible execution faults may cool new calls to the same tool without ending the organization or unrelated people.

Unavailable providers retain a resource reason and recovery/remediation boundary rather than change the person's deliberate intent.

Cancellation, persistence failure, shutdown, and state-integrity faults retain their framework-level propagation rather than become synthetic personal answers.

See [Model and Tool Execution](Model_and_Tool_Execution.md) for the distinct retry and cooldown contracts.
