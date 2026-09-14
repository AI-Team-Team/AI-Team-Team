"""ATTManager shutdown and invocation lifecycle coordination."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Iterable, Optional, Tuple

from ..agent import Agent
from ..exceptions import AgentInvocationDependencyError

if TYPE_CHECKING:
    from .facade import ATTManager


class LifecycleService:
    """Owns shutdown ordering and active Agent invocation accounting."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    def _live_invocation_chain_locked(self) -> Tuple[Tuple[str, str], ...]:
        """Returns the calling task's live invocation chain while the runtime gate is held."""
        manager = self.manager
        return tuple(
            entry
            for entry in manager._agent_invocation_chain.get()
            if entry[1] in manager._active_agent_invocation_tokens
        )

    @staticmethod
    def _path_exists(
        start_agent_id: str,
        target_agent_id: str,
        adjacency: dict[str, set[str]],
    ) -> bool:
        pending = [start_agent_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target_agent_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(adjacency.get(current, ()))
        return False

    def _reserve_wait_edges_locked(
        self,
        source_agent_id: str,
        target_agent_ids: Iterable[str],
    ) -> Tuple[Tuple[str, str], ...]:
        """Atomically validates and reference-counts synchronous Agent dependencies."""
        manager = self.manager
        targets = tuple(dict.fromkeys(target_agent_ids))
        edges = tuple((source_agent_id, target_agent_id) for target_agent_id in targets)
        adjacency: dict[str, set[str]] = {}
        for (edge_source, edge_target), count in manager._agent_wait_edge_counts.items():
            if count > 0:
                adjacency.setdefault(edge_source, set()).add(edge_target)

        for edge_source, edge_target in edges:
            if edge_source == edge_target:
                raise AgentInvocationDependencyError(
                    "Synchronous Agent work cannot depend on the same Agent identity."
                )
            if manager._agent_wait_edge_counts.get((edge_source, edge_target), 0) > 0:
                continue
            if self._path_exists(edge_target, edge_source, adjacency):
                raise AgentInvocationDependencyError(
                    "Synchronous Agent work would create an Agent invocation wait cycle "
                    f"between {edge_source!r} and {edge_target!r}."
                )
            adjacency.setdefault(edge_source, set()).add(edge_target)

        for edge in edges:
            manager._agent_wait_edge_counts[edge] = (
                manager._agent_wait_edge_counts.get(edge, 0) + 1
            )
        return edges

    def _release_wait_edges_locked(
        self,
        edges: Iterable[Tuple[str, str]],
    ) -> None:
        manager = self.manager
        for edge in edges:
            count = manager._agent_wait_edge_counts.get(edge, 0)
            if count <= 1:
                manager._agent_wait_edge_counts.pop(edge, None)
            else:
                manager._agent_wait_edge_counts[edge] = count - 1

    @asynccontextmanager
    async def reserve_synchronous_dependencies(
        self,
        target_agent_ids: Iterable[str],
    ):
        """Reserves all dependencies before an operation creates synchronously awaited work."""
        manager = self.manager
        reserved_edges: Tuple[Tuple[str, str], ...] = ()
        async with manager._runtime_gate:
            dependency_chain = self._live_invocation_chain_locked()
            targets = tuple(dict.fromkeys(target_agent_ids))
            if dependency_chain and targets:
                dependency_ids = {agent_id for agent_id, _ in dependency_chain}
                blocking_ids = sorted(dependency_ids.intersection(targets))
                if blocking_ids:
                    raise AgentInvocationDependencyError(
                        "Synchronous Agent work cannot include an Agent whose invocation "
                        "is already in the current dependency chain: "
                        + ", ".join(blocking_ids)
                    )
                reserved_edges = self._reserve_wait_edges_locked(
                    dependency_chain[-1][0],
                    targets,
                )
        try:
            yield
        finally:
            if reserved_edges:
                async with manager._runtime_gate:
                    self._release_wait_edges_locked(reserved_edges)

    async def close(self) -> None:
        """Cancels external waits, commits accepted state, and releases resources."""
        manager = self.manager
        if manager._closed:
            return
        manager._closing = True
        manager._formations.cancel_for_shutdown()
        await manager._memory.close()
        current = asyncio.current_task()
        active_tasks = {
            task
            for task in (
                manager._llm_tasks
                | manager._emergency_tasks
                | manager._formations.tasks
                | manager._formation_operation_tasks
            )
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
        dependency_edges: Tuple[Tuple[str, str], ...] = ()
        async with manager._runtime_gate:
            if manager._closing:
                raise RuntimeError("ATTManager is closing and rejects new agent invocations.")
            registered = manager._agents_by_id.get(agent.agent_id) is agent
            if (not registered and not allow_runtime) or (agent.lifecycle_state != "active"):
                raise RuntimeError("Agent is not an active identity in this manager.")
            dependency_chain = self._live_invocation_chain_locked()
            if any(agent_id == agent.agent_id for agent_id, _ in dependency_chain):
                raise AgentInvocationDependencyError(
                    "Nested work cannot wait for an Agent invocation that is already "
                    "in its synchronous dependency chain."
                )
            if dependency_chain:
                dependency_edges = self._reserve_wait_edges_locked(
                    dependency_chain[-1][0],
                    (agent.agent_id,),
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
                        self._release_wait_edges_locked(dependency_edges)
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
                        self._release_wait_edges_locked(dependency_edges)
