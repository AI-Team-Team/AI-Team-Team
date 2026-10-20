"""Live handles remain manager-owned; immutable provenance survives callers."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ai_team_team.core.activity.contracts import OperationScope


@dataclass(frozen=True)
class ExecutionContext:
    agent_id: str
    invocation_id: str | None
    generation: int
    scope: OperationScope


@dataclass(frozen=True)
class ExecutorCall:
    execution_id: str
    owner_agent_id: str
    scope: OperationScope
    tool: Any
    arguments: tuple
    keywords: Any
    report_health: Any = None


@dataclass
class Job:
    execution_id: str
    context: ExecutionContext
    tool: Any
    args: tuple
    kwargs: Any
    call_id: str
    claims: tuple
    sources: tuple
    retry: dict
    started: asyncio.Event = field(default_factory=asyncio.Event)
    started_monotonic: float | None = None
    authority: Any = None
    task: Any = None
    result: Any = None
    error: Any = None
    cancellation_requested: bool = False
    pending_threads: set = field(default_factory=set)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    control_id: str | None = None
    health_samples: dict = field(default_factory=dict)
    health_updated: asyncio.Event = field(default_factory=asyncio.Event)
    health_task: Any = None
    thread_outcome: Any = None
    late_settlement_started: bool = False
    awaiting_thread_result: bool = False
    outcome_task: Any = None
    attempts: int = 0
    transient_delivery_invocation: str | None = None


class CallableExecutor:
    """The callable return confirms only the operation implemented by that tool."""

    async def execute(self, call, job):
        import inspect
        args, kwargs = call.arguments, call.keywords
        if inspect.iscoroutinefunction(call.tool.func):
            return await call.tool.invoke_validated(*args, **kwargs)
        task = asyncio.create_task(asyncio.to_thread(call.tool.func, *args, **kwargs))
        job.pending_threads.add(task)
        def completed(future):
            job.pending_threads.discard(future)
            if not future.cancelled():
                error = future.exception()
                job.thread_outcome = (error is None, future.result() if error is None else error)
        task.add_done_callback(completed)
        # A cancelled coroutine is not proof that its synchronous worker ended.
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            job.awaiting_thread_result = True
            raise
