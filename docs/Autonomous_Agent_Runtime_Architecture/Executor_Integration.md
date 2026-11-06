# Registered Tool and Executor Integration

ATT lets the Host bind custom operations to the common execution service while retaining the actual Agent owner, captured scope, resource reservations, and accepted outcome evidence.

This reference specifies the registration values and runtime interfaces used by both foreground and background-capable tools.

## ToolExecutionContract Fields

Import `ToolExecutionContract` from `ai_team_team.core.activity.contracts`.

The record is immutable, uses strict validation, and forbids unknown fields.

Python callers supply tuples for the tuple fields; their JSON representation is an array.

| Field | Required or default | Legal values and meaning |
| --- | --- | --- |
| `effects` | Required, nonempty tuple | Unique entries from `read_only`, `artifact_write`, `domain_mutation`, `self_modification`, and `undeclared`. |
| `background_allowed` | Required | Literal boolean declaring eligibility for explicit background admission and automatic detachment. |
| `required_scope` | Required | `personal`, `agent_team`, or `either`; the captured invocation scope and actual operation authorization are still preserved. |
| `mutation_safety` | `"none"` | `none`, `managed_lease`, `isolated`, or `trusted_host`; the actual integration must supply the stated mutation protection. |
| `cancellation` | `"none"` | `none`, `cooperative`, `provider`, or `isolated`; capability and acknowledgement remain distinct from a stop request. |
| `suspension` | `"none"` | `none` or `provider`; provider suspension requires an asynchronous binding hook. |
| `health_signals` | `()` | Unique entries from `heartbeat`, `progress`, and `provider`. |
| `heartbeat_timeout_seconds` | `None` | Optional finite positive number; requires `heartbeat` in `health_signals`. |
| `progress_timeout_seconds` | `None` | Optional finite positive number; requires `progress` in `health_signals`. |

Any `self_modification` or `undeclared` effect prohibits `background_allowed=True`.

A detachable `artifact_write` or `domain_mutation` requires `mutation_safety` other than `none`, including when several effects are declared together.

`managed_lease` describes ATT-authorized mutation boundaries, `isolated` describes an actual isolated integration, and `trusted_host` assigns the integration responsibility explicitly to the Host.

Selecting one of these labels alone does not isolate arbitrary Python, grant ACL access, or make an external operation stoppable.

`required_scope="personal"` permits the person's own authority during a team invocation without changing its provenance; `agent_team` requires current membership in the captured team, and `either` accepts either captured scope.

Tool-specific authorization still checks each protected operation rather than treating `either` as combined authority from several memberships.

Omitting the entire execution contract gives a custom tool `effects=("undeclared",)`, `background_allowed=False`, and `required_scope="either"`.

Retry declarations such as `retry_safe` and `tool_execution_retry_policy`, and result storage such as `result_storage="protected"` or `"transient"`, remain separate registration fields.

## Executor Binding and ExecutorCall

`manager.register_executor(name, executor)` requires a unique nonblank name and an object implementing `async execute(call)`.

The default `callable` binding invokes the registered function and remains reserved by the service.

Select a custom binding with `manager.register_tool(..., executor="binding-name", execution_contract=...)`.

Each real attempt receives an `ExecutorCall` with these fields:

| Field | Content |
| --- | --- |
| `execution_id` | The same admitted execution identity across retries and detachment. |
| `owner_agent_id` | The actual continuing person that owns the operation. |
| `scope` | The captured `PersonalScope` or `AgentTeamScope`. |
| `tool` | The registered `Tool` and its captured execution declaration. |
| `arguments` | Validated positional arguments as a tuple. |
| `keywords` | Validated keyword arguments. |
| `report_health` | Awaitable callback used as `await call.report_health(health, evidence_kind, evidence=None)`. |

The binding receives neither a second Agent persona nor an owner's mutable Working Context field.

Background workers use deliberately seeded execution context, while coordinated foreground-only controls retain their personal invocation context through the same admission and resource checks.

An executor returns the result of the registered operation or raises an appropriate typed tool exception; it does not manufacture another model observation or directly rewrite accepted execution records.

Provider or external-job identifiers describe only what the operation actually returned and do not certify remote completion.

The service applies the captured typed retry policy around actual attempts, so an adapter must account explicitly for any additional upstream retries it performs itself.

## Cancellation and Suspension Hooks

| Declaration | Binding requirement and factual meaning |
| --- | --- |
| `cancellation="none"` | No declared way to confirm a running operation stopped; queued cancellation can still prevent dispatch. |
| `cancellation="cooperative"` | The running coroutine must actually cooperate with cancellation; a synchronous function on the default callable binding cannot declare this capability. |
| `cancellation="provider"` or `"isolated"` | The selected binding must have a callable `cancel(execution_id)` hook; only literal `True` acknowledges the declared stop. |
| `suspension="provider"` | The selected binding must implement `async suspend(execution_id)`; only literal `True` acknowledges suspension. |

Stop hooks may be asynchronous, or synchronous where supported by the cancellation binding; synchronous stop work runs off the event loop.

`executions.cancellation_grace_seconds` bounds external hook waiting without imposing a persistence flush deadline.

A false result, missing acknowledgement, timeout, or local wait cancellation leaves factual uncertainty rather than proving a stopped external operation.

Unacknowledged suspension falls back to the supported stop protocol, and suspension is retained control evidence over the existing five execution states.

Confirmed returned outcomes retain their local finalization even when cancellation races their result commit.

Late authoritative framework failures remain observable through cancellation and shutdown; an ordinary external stop failure is separate from whether execution completion was confirmed.

## ResourceClaim and Resolver Contract

Import `ResourceClaim` from `ai_team_team.core.execution`.

| Field | Required or default | Meaning |
| --- | --- | --- |
| `namespace` | Required nonblank string | `library` selects ATT-managed library paths; `global` creates conservative shared exclusion; other names describe declared external resource domains. |
| `resource_id` | Required nonblank string | Actual registered library ID or stable shared-resource identity. |
| `path` | `""` | Canonical relative path; empty denotes the library/resource root where applicable. |
| `access` | `"write"` | `read` or `write`. |
| `subtree` | `False` | Whether the claim includes descendants of its path. |

The Host supplies a synchronous, side-effect-free `resource_resolver(scope, arguments)` returning `ResourceClaim` records or strictly valid equivalent mappings.

`arguments` is the signature-bound parameter mapping with defaults applied, and the resolver must not return an awaitable.

Library paths use ATT's normalized virtual spelling without traversal, and library identity/physical targets are revalidated after waits and at protected access.

Two read claims can coexist; a conflicting write, matching path, claimed subtree, or global exclusion serializes access across owners.

File moves claim both endpoints, and managed links include actual target authority rather than only the alias spelling.

Without a resolver, ordinary undeclared/custom resource use receives conservative global exclusion; pure self-modification has its own foreground coordination rules.

Returning `()` explicitly declares source-free independence and must match the operation's actual behavior.

Registered foreground-only tools use the same admission, executor binding, resource checks, attempt evidence, and result acceptance as background-capable tools while retaining their personal Session.

Declaring `self_modification` does not exempt other effects or explicit resource claims from those checks.

A pure self-modification control acquires no implicit shared-resource reservation or managed-file authority, and its source provenance remains opaque unless the Host explicitly declares a source-free resolver.

Personal coordination may wait for another person's model activity only through an eligible foreground control without shared-resource claims; ordinary executors use addressed mail instead.

The nested person's invocation acquires its own tool-resource context while the originating execution retains its revocable authority and dependency edges.

Nonempty global/external claims retain opaque source provenance and fail closed under restrictive retained-result source revalidation; they are not equivalent to an empty source-free resolver.

Resource serialization allows semantic last-writer overwrite and does not add optimistic read-modify-write conflict detection.

## Health Reports and Deadlines

The callback accepts only the current runtime's live, actually started execution and a signal declared in `health_signals`.

`health` is `healthy`, `degraded`, `stalled`, `error`, or `unknown`, independently of execution state and attention.

| Evidence key | Accepted value |
| --- | --- |
| `sequence` | Nonnegative integer counter; booleans are rejected. |
| `units_completed` | Nonnegative integer counter; booleans are rejected. |
| `provider_status` | `running`, `completed`, `failed`, `stalled`, or `unavailable`. |

Unknown evidence keys, arbitrary text, results, private bodies, and raw arguments are rejected.

A report changes health evidence rather than completing the execution or acknowledging owner attention.

No automatic stall timer is installed when both timeout fields are `None`.

For each configured signal, its first deadline starts at actual executor start; an accepted healthy report refreshes only that signal's monotonic sample.

Missing heartbeat support never becomes a silence-based stall, and a heartbeat does not reset a separately expired progress deadline.

Only consecutive identical nonhealthy reports coalesce; returning to a previous state after another transition creates a new ordered observation.

Accepted samples, timeout decisions, and observation order share protection, so delayed commits cannot publish an obsolete stall over a newer sample or lose a crossed deadline.

A healthy sample accepted before observer cancellation still refreshes its live deadline.

## Example: Progress-Aware Custom Binding

This registration fragment assumes a configured manager and its existing model bindings.

The example operation uses no shared source or filesystem resource, so its explicit empty resolver is appropriate.

```python
from ai_team_team.core.activity.contracts import ToolExecutionContract


class ProgressExecutor:
    async def execute(self, call):
        await call.report_health("healthy", "heartbeat", {"sequence": 0})
        result = await call.tool.invoke_validated(*call.arguments, **call.keywords)
        await call.report_health("healthy", "progress", {"units_completed": 1})
        return result


async def count_records() -> str:
    return "The operation counted 7 records."


manager.register_executor("progress", ProgressExecutor())
manager.register_tool(
    count_records,
    executor="progress",
    execution_contract=ToolExecutionContract(
        effects=("read_only",),
        background_allowed=True,
        required_scope="personal",
        cancellation="cooperative",
        health_signals=("heartbeat", "progress"),
        heartbeat_timeout_seconds=30.0,
        progress_timeout_seconds=60.0,
    ),
    resource_resolver=lambda scope, arguments: (),
)
```

Use the [background-task API](../user/API_Reference.md#registered-execution-and-background-tasks) to admit and inspect the operation with its actual owner.

Bindings and callables must be registered again by the Host after restoration; historical tool names and external handles do not restart work.

The [execution service](../../src/ai_team_team/core/manager/executions/), [strict contract model](../../src/ai_team_team/core/activity/contracts/execution.py), and [binding/health regressions](../../test/test_att/test_background_tasks/test_timing_and_bindings.py) provide implementation and behavioral evidence.
