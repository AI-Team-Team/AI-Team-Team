"""Bounded CI observers with pre-cancellation, payload-free runtime diagnostics."""

import asyncio
import json
import sys
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path


DEFAULT_RUNTIME_TIMEOUT = 60


def task_state(task):
    if task is None:
        return None
    frames = task.get_stack(limit=1)
    frame = frames[0] if frames else None
    return {
        "done": task.done(), "cancelled": task.cancelled(), "cancelling": task.cancelling(),
        "location": (f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}"
                     if frame is not None else None),
    }


def runtime_state(manager):
    """Expose identifiers, states, and counts, never bodies, arguments or errors."""
    activity = manager._activity
    records = manager._records
    governance = manager._governance
    retained = records.snapshot()
    persistence = manager._persistence
    active_write = persistence._active_task
    return {
        "state_version": manager._state_version,
        "accepted_operations": len(records.receipts),
        "record_counts": dict(sorted(Counter(row.table_name for row in retained).items())),
        "model_request_counts": dict(Counter(row.values["agent_id"] for row in retained if row.table_name == "model_requests")),
        "persistence": {"active_write": active_write is not None and not active_write.done(),
                        "pending_delta": persistence._pending_snapshot is not None,
                        "error_type": type(persistence._error).__name__ if persistence._error is not None else None},
        "governance_states": dict(Counter(str(item.status) for item in governance.rounds.values())),
        "workers": len(activity.workers), "ready": activity.ready.qsize(),
        "dispatch_tasks": len(activity.dispatch_tasks), "tool_tasks": len(activity.tool_tasks),
        "provider_tasks": len(activity.models.tasks),
        "admitted_model_requests": activity.models.admitted_requests,
        "scheduler": task_state(activity.scheduler),
        "emergency_tasks": [task_state(task) for task in manager._emergency_tasks],
        "locks": {"runtime": manager._runtime_gate.locked(), "activity": activity.lock.locked(),
                  "records": records.lock.locked()},
        "wait_edges": [{"source_agent_id": source, "target_agent_id": target, "count": count}
                       for (source, target), count in sorted(manager._agent_wait_edge_counts.items())],
        "suspended_workers": [{"agent_id": resume.session.agent_id, "waits": resume.waits,
                               "queued": resume.queued, "worker": task_state(resume.worker)}
                              for resume in activity.suspended_workers.values()],
        "sessions": {agent_id: {"active": session.active, "running": session.running,
                                "queued": session.queued, "intent": session.intent,
                                "availability": session.availability,
                                "failure_type": type(session.failure).__name__ if session.failure is not None else None,
                                "worker": task_state(getattr(session, "worker", None))}
                     for agent_id, session in sorted(activity.sessions.items())},
    }


@asynccontextmanager
async def runtime_watchdog(manager, *, timeout=DEFAULT_RUNTIME_TIMEOUT, label="Runtime observer"):
    """Only this deadline is translated; domain timeouts and cancellation escape."""
    loop = asyncio.get_running_loop()
    when = loop.time() + timeout
    captured = {}
    did_expire = False
    domain_timeout = None
    deadline = asyncio.timeout(None)

    def expired():
        nonlocal did_expire
        did_expire = True
        try:
            captured.update(runtime_state(manager))
        except Exception as error:
            captured["diagnostic_error_type"] = type(error).__name__
        # Emit before cancellation: accepted commit cleanup may still be waiting
        # on a slow writer, and its caller must not abandon that transaction.
        try:
            print(f"{label} exceeded {timeout:g} seconds. Runtime state: "
                  f"{json.dumps(captured, sort_keys=True)}", file=sys.stderr, flush=True)
        finally:
            # Chaining the native timeout after capture avoids relying on the
            # unspecified ordering of two timers at the same timestamp.
            deadline.reschedule(loop.time())

    handle = None
    try:
        async with deadline:
            handle = loop.call_at(when, expired)
            try:
                yield
            except TimeoutError as error:
                domain_timeout = error
                raise
    except TimeoutError as error:
        if error is domain_timeout or not deadline.expired():
            raise
        raise AssertionError(f"{label} exceeded {timeout:g} seconds. Runtime state: "
                             f"{json.dumps(captured, sort_keys=True)}") from None
    else:
        if did_expire:
            # Completion between capture and native cancellation, or deliberate
            # cancellation suppression, cannot turn expiry into a passing test.
            raise AssertionError(f"{label} exceeded {timeout:g} seconds. Runtime state: "
                                 f"{json.dumps(captured, sort_keys=True)}")
    finally:
        if handle is not None:
            handle.cancel()


async def wait_for_runtime(manager, awaitable, *, timeout=DEFAULT_RUNTIME_TIMEOUT, label="Runtime observer"):
    async with runtime_watchdog(manager, timeout=timeout, label=label):
        return await awaitable
