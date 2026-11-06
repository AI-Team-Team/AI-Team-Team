# Registered Execution and Background Tasks

ATT allows Agents to run registered tool operations in the background while continuing other personal activity.

This document explains task registration, admission, resource coordination, result access, and execution controls in ATT.

Each task remains owned by the Agent that started it and continues the same registered operation across foreground waiting and background execution.

It does not create another model-driven copy, change personal memory, or decide whether a business objective is complete.

## Registration and Admission

Every tool declares its effects, required scope, background permission, and applicable mutation safety independently of retry policy and result storage.

Undeclared custom tools remain foreground-only with conservative shared-resource exclusion.

Only an affirmative `ToolExecutionContract(background_allowed=True, ...)` allows explicit background admission or automatic detachment.

The [executor integration reference](Autonomous_Agent_Runtime_Architecture/Executor_Integration.md) lists every contract field, valid combination, binding hook, resource claim, and health-report format, with a custom binding example.

Self-modifying and undeclared effects cannot run in the background, and detachable mutations require a declared safety contract.

Private DocLib writes create work artifacts rather than modifying the owner's identity, instructions, model binding, Working Context, or lifecycle.

The built-in private write, move, and delete tools declare background-eligible artifact effects with managed-lease safety; private ownership, archive protection, path validation, and library/resource locking still apply.

Executor results and later judgments return to the same owner's personal activity rather than allowing a background worker to rewrite that person's model context.

The Host registers executor bindings; models cannot supply arbitrary Python, a callable, an executor, another owner, or policy overrides.

Strict arguments, current scope, authorization, auditors, resource claims, and an execution identity precede actual dispatch.

```python
from ai_team_team.core.activity.contracts import ToolExecutionContract

manager.register_tool(
    inspect_records,
    execution_contract=ToolExecutionContract(
        effects=("read_only",), background_allowed=True, required_scope="personal",
    ),
    resource_resolver=lambda scope, arguments: (),
)
handle = await manager.start_background_task("inspect_records", {}, actor=owner)
```

This fragment assumes an existing `inspect_records` callable and a configured manager; the complete executable example appears below.

An empty resolver is an explicit source-free independence declaration, not a default for tools that access shared files or external state.

## Same Execution, Different Observation

The default automatic-detachment threshold is 120 seconds from actual executor dispatch, including subsequent retry and backoff but excluding initial queue and preflight time.

Explicit background admission returns a handle after its receipt without waiting for an execution result.

An ordinary foreground call returns either its completed observation or one handle when eligible work crosses the threshold.

The operation is never restarted merely to detach, and its original model call does not later receive a second tool reply.

Crossing the detachment threshold is not a failure, cancellation, retry, or execution-deadline expiry.

Later outcomes notify only the same owner, who can deliberately inspect the task and result.

## Independent Task Dimensions

| Dimension | Values and meaning |
| --- | --- |
| Execution | `queued`, `running`, `completed`, `failed`, or `cancelled`; describes the registered operation's factual state. |
| Health | `healthy`, `degraded`, `stalled`, `error`, or `unknown`; depends only on declared execution evidence. |
| Attention | `none`, `required`, or `acknowledged`; records the owner's explicit handling independently. |
| Uncertainty | `outcome_unconfirmed=True` retains the last-confirmed execution fact without claiming its current external state is known. |
| Suspension | Acknowledged provider control evidence exposed by `TaskView.suspended`, not a sixth execution state. |

A returned remote job ID confirms only the registered submission operation, not completion of the remote job or business objective.

Descriptions and labels are metadata and do not set execution, health, or attention state.

Lists and searches inspect owner-filtered metadata without scanning protected result bodies.

Reading a result does not acknowledge attention; `acknowledge_background_task()` is a separate explicit operation.

Reading a task notification also does not acknowledge the task's attention state.

Execution health uses declared signals and retained evidence: an unsupported heartbeat or a legitimate lack of intermediate output is not itself a fault.

`unknown` represents insufficient supported evidence, while `stalled` represents suspected lack of progress even when the execution still runs.

A health observation alone does not replay, restart, cancel, or mark an execution failed; actual terminal outcomes and explicit control acknowledgements retain their separate authority.

The [signal and deadline contract](Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#health-reports-and-deadlines) defines optional timers independently of the detachment threshold.

## Model-Visible Task Summary

Every ordinary personal model request includes a lightweight task summary, including when all counts are zero.

It covers the same owner's explicit background and detached executions across personal and team scopes, without including task bodies or creating another personal activity.

Foreground executions enter these counts only if they detach.

| Summary count | Included executions |
| --- | --- |
| Queued or running | Executions in that state with no unconfirmed outcome and no acknowledged suspension. |
| Completed, failed, or cancelled | Terminal executions whose attention is still `required`. |
| Suspended | Executions with an acknowledged suspension whose last execution state remains `running`. |
| Stalled health | Executions whose latest health observation is `stalled` and whose attention is not `acknowledged`. |
| Requiring attention | Executions whose attention is `required`, independently of execution or health state. |
| Unconfirmed outcomes | Executions retaining `outcome_unconfirmed=True`. |

These counts can overlap: one running execution may also have stalled health and require attention.

Adding the counters therefore does not produce a total number of tasks.

Acknowledging a terminal task removes it from the terminal attention count while preserving its history for authorized list, search, inspection, and result access.

Task counts do not read results, acknowledge attention, or decide that business work is complete.

## Resources, Writes, and Retries

Canonical `ResourceClaim` values identify read/write footprints, directory descendants, and actual managed-link targets across owners.

Conflicting operations serialize, while independent operations can proceed concurrently.

Serialized writes may overwrite content read earlier; ATT adds no optimistic write-version requirement or overwrite confirmation for ordinary collaborative writes.

Read-continuation version checks remain necessary to reject stale multi-part reads and do not change that write contract.

Aliases, managed links, current membership, and ACLs are revalidated at applicable attempt, physical access, and result-acceptance boundaries.

Tool effects, `retry_safe`, typed transient failures, retry count, and backoff remain separate declarations.

Permission and business denials do not cause automatic replay, and eligible execution faults may apply the configured per-Agent, per-tool cooldown.

`activity.tool_cooldown_seconds` defaults to 600 seconds; `activity.cooldown_downtime="include"` counts offline time, while `"exclude"` preserves the remaining cooldown.

Executors holding shared reservations cannot synchronously wait for nested personal model activity; they send addressed information instead.

## Protected Results and Stopping

Results use owner-authorized storage or transient delivery according to their registration.

Inspecting a lawfully retained result after restoration does not require rebinding its historical tool or executor and does not reconnect or rerun that operation.

`read_background_task_result()` uses the effective model's content-token budget and supports line, character, and file-version continuation.

By default, an owner may read a result lawfully acquired and committed before source permission was later revoked.

Setting `executions.retain_results_after_source_revocation=False` requires current original-source authority without deleting history, borrowing another scope, or rereading an external source automatically.

That policy does not authorize a result whose source access failed at acceptance, and it never overrides transient storage.

A stop request is retained separately from actual acknowledgement; request, timeout, and Python task cancellation alone do not prove an external operation stopped.

Queued work can cancel without dispatch, cooperative coroutines can acknowledge cancellation, and declared provider or isolated cancellation requires a real binding hook.

Bindings declaring `suspension="provider"` implement `async suspend(execution_id)` and acknowledge only by returning literal `True`.

Unacknowledged suspension falls back to termination, and unconfirmed stopping retains uncertainty with a Host risk event.

External hook waiting is bounded; returned outcomes and accepted local persistence commits settle without an arbitrary flush timeout.

Before capturing retained death, the manager drains already returned local outcomes for that owner while preserving source authorization checks.

New managed effects remain fenced after the owner dies or execution authority is revoked.

Restoration retains interrupted evidence and owner references without replaying, polling, or reconnecting old external work.

## Complete Offline Example

Run `./venv/bin/python examples/background_tasks.py` from the repository after installation.

The file uses `DemoClient` from the adjacent [personal activity example](../examples/personal_activity.py); save both files together when copying them into another project.

The Host explicitly suppresses ordinary reminders for this example and reads the accepted result itself, so the example needs no provider network calls.

Its async observer runs on the event loop; a synchronous callback runs in a worker thread and must use a thread-safe loop handoff before touching asyncio primitives.

<!-- runnable: examples/background_tasks.py -->

```python
"""Inspect an owner-authorized background result without a network provider."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import SuppressionPreference, ToolExecutionContract
from personal_activity import DemoClient


async def run_demo(workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    client = DemoClient(answer=False)
    owner = Agent("Owner", "Researcher", client)
    async with ATTManager(owner, ATTConfig(workspace_root=str(workspace)),
                          db_path=str(workspace / "tasks.sqlite")) as manager:
        manager.register_llm_client("demo", client)
        # This Host-controlled demo inspects results explicitly instead of
        # waking the owner for ordinary task reminders. Delivery still occurs.
        await manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=owner)
        committed = asyncio.Event()

        async def observe(event: str, metadata: dict[str, Any]) -> None:
            if event == "execution_outcome_committed":
                committed.set()

        manager.on_system_event = observe

        async def count_records() -> str:
            return "The example counted 7 records."

        manager.register_tool(
            count_records,
            execution_contract=ToolExecutionContract(
                effects=("read_only",), background_allowed=True, required_scope="personal",
            ),
            resource_resolver=lambda scope, arguments: (),
        )
        handle = await manager.start_background_task("count_records", {}, actor=owner)
        # This is an observer deadline, not a persistence flush timeout.
        async with asyncio.timeout(30):
            await committed.wait()
        view = manager.inspect_background_task(handle.execution_id, actor=owner)
        result = await manager.read_background_task_result(handle.execution_id, actor=owner)
        assert view.execution_state == "completed"
        assert view.attention_state == "required"
        assert "7 records" in result.content
        assert manager.inspect_background_task(handle.execution_id, actor=owner).attention_state == "required"
        acknowledged = await manager.acknowledge_background_task(handle.execution_id, actor=owner)
        assert client.calls == 0
        await manager.save_state()
    return {"admission": handle.status, "execution": view.execution_state,
            "attention": acknowledged.status, "durability": handle.durability}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="att-task-example-") as directory:
        result = asyncio.run(run_demo(Path(directory)))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
```

The returned summary distinguishes background admission, factual execution completion, attention acknowledgement, and durability.

See [API Reference](user/API_Reference.md), [Tool System](Tool_System.md), [Personal Activity](Personal_Activity.md), [State Persistence](State_Persistence.md), and the [execution flowchart](flowcharts/Background_Tasks.md).
