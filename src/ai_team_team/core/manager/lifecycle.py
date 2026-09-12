"""ATTManager shutdown and invocation lifecycle coordination."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Optional

from ..agent import Agent
from ..exceptions import AgentInvocationDependencyError

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
        await manager._memory.close()
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
            for agent in manager._agents_by_id.values():
                if agent._manager is manager:
                    agent._manager = None
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
            dependency_chain = tuple(
                entry
                for entry in manager._agent_invocation_chain.get()
                if entry[1] in manager._active_agent_invocation_tokens
            )
            if any(agent_id == agent.agent_id for agent_id, _ in dependency_chain):
                raise AgentInvocationDependencyError(
                    "Nested work cannot wait for an Agent invocation that is already "
                    "in its synchronous dependency chain."
                )
            manager._starting_invocations += 1
        invocation = agent.invocation_guard()
        invocation_entered = False
        starting_counted = True
        try:
            await invocation.__aenter__()
            invocation_entered = True
            async with manager._runtime_gate:
                manager._starting_invocations -= 1
                starting_counted = False
                manager._active_invocations += 1
                invocation_id = uuid.uuid4().hex
                manager._active_agent_invocation_tokens.add(invocation_id)
        except BaseException:
            try:
                if starting_counted:
                    async with manager._runtime_gate:
                        manager._starting_invocations -= 1
            finally:
                if invocation_entered:
                    await invocation.__aexit__(None, None, None)
            raise
        chain_token = manager._agent_invocation_chain.set(
            (*dependency_chain, (agent.agent_id, invocation_id))
        )
        try:
            yield
        finally:
            try:
                await invocation.__aexit__(None, None, None)
            finally:
                try:
                    manager._agent_invocation_chain.reset(chain_token)
                finally:
                    async with manager._runtime_gate:
                        manager._active_agent_invocation_tokens.discard(
                            invocation_id
                        )
                        manager._active_invocations -= 1
