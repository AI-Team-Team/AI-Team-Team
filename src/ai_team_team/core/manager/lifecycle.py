"""ATTManager shutdown and invocation lifecycle coordination."""

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Optional

from ..agent import Agent

if TYPE_CHECKING:
    from .facade import ATTManager


class LifecycleService:
    """Owns shutdown ordering and active Agent invocation accounting."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    async def close(self) -> None:
        """Cancels external waits, commits accepted state, and releases resources."""
        manager = self.manager
        if manager._closed:
            return
        manager._closing = True
        current = asyncio.current_task()
        active_tasks = {
            task
            for task in manager._llm_tasks | manager._emergency_tasks
            if not task.done() and task is not current
        }
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            # Deliver cancellation without waiting on providers that suppress it.
            await asyncio.sleep(0)
            for task in active_tasks:
                if task.done():
                    try:
                        task.result()
                    except BaseException:
                        pass

        await manager._callbacks.close()
        reset_error: Optional[BaseException] = None
        try:
            await manager.broker.reset_processing_for_shutdown()
        except BaseException as exc:
            reset_error = exc
        try:
            await manager._persistence.close()
        finally:
            manager._closed = True
        if reset_error is not None:
            raise reset_error

    @asynccontextmanager
    async def agent_invocation(self, agent: Agent, *, allow_runtime: bool = False):
        """Starts a model invocation atomically against restore and retirement."""
        manager = self.manager
        async with manager._runtime_gate:
            if manager._closing:
                raise RuntimeError("ATTManager is closing and rejects new agent invocations.")
            registered = manager._agents_by_id.get(agent.agent_id) is agent
            if (not registered and not allow_runtime) or (agent.lifecycle_state != "active"):
                raise RuntimeError("Agent is not an active identity in this manager.")
            manager._starting_invocations += 1
        invocation = agent.invocation_guard()
        try:
            await invocation.__aenter__()
        except BaseException:
            async with manager._runtime_gate:
                manager._starting_invocations -= 1
            raise
        async with manager._runtime_gate:
            manager._starting_invocations -= 1
            manager._active_invocations += 1
        try:
            yield
        finally:
            try:
                await invocation.__aexit__(None, None, None)
            finally:
                async with manager._runtime_gate:
                    manager._active_invocations -= 1
