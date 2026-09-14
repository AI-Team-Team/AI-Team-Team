import asyncio
import json
import shutil
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentInvocationDependencyError,
    ToolResultStatus,
)
from ai_team_team.core.tool_runtime import ToolExecutor


class EchoClient:
    async def generate(self, **kwargs):
        if kwargs.get("require_json"):
            return json.dumps({"is_healthy": True, "reason": "Synthetic audit."})
        return "Final Answer: done"

    def supports_native_tool_calling(self):
        return False


class CoordinatedDelegatingClient(EchoClient):
    def __init__(self, barrier):
        self.barrier = barrier
        self.target_agent_id = None
        self.calls = 0

    async def generate(self, **kwargs):
        if kwargs.get("require_json"):
            return await super().generate(**kwargs)
        self.calls += 1
        if self.calls == 1:
            await self.barrier.wait()
            return (
                "Action: dispatch_subagent(task='Review this task', "
                "team_purpose='Delegated review', "
                "member_configs={'Helper1': {}, 'Helper2': {}}, "
                f"existing_member_ids={[self.target_agent_id]!r})"
            )
        return await super().generate(**kwargs)


class TestDelegationDependencies(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-delegation-dependency-")
        self.client = EchoClient()
        self.manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir, subagent_discussion_rounds=1),
        )
        self.manager.register_llm_client("echo", self.client)
        self.parent = self.manager.create_agent_team(self.manager.root_ai)
        self.caller = self.parent.members[0]
        self.ancestor = self.parent.members[1]
        self.third = self.parent.members[2]

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _dispatch_with_existing(self, agent_id):
        executor = ToolExecutor(self.parent, self.caller, self.manager)
        tools = self.manager.get_available_tools(self.parent, self.caller)
        return await executor.execute(
            "dispatch_subagent",
            kwargs={
                "task": "Review the evidence.",
                "team_purpose": "Dependency review",
                "member_configs": {"ReviewerA": {}, "ReviewerB": {}},
                "existing_member_ids": [agent_id],
            },
            tools=tools,
        )

    async def test_direct_self_invitation_is_rejected_before_formation(self):
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        agents_before = set(self.manager._agents_by_id)

        async with self.manager.agent_invocation(self.caller):
            result = await self._dispatch_with_existing(self.caller.agent_id)

        self.assertIs(result.status, ToolResultStatus.BUSINESS_ERROR)
        self.assertEqual(result.error_kind, "business_error")
        self.assertIn("cannot invite itself", result.content)
        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager.libraries), libraries_before)
        self.assertEqual(set(self.manager._agents_by_id), agents_before)

    async def test_async_invitation_does_not_reserve_an_invocation_dependency(self):
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        agents_before = set(self.manager._agents_by_id)

        async with self.manager.agent_invocation(self.ancestor):
            async with self.manager.agent_invocation(self.caller):
                result = await self._dispatch_with_existing(
                    self.ancestor.agent_id
                )

        self.assertIs(result.status, ToolResultStatus.SUCCESS)
        self.assertIn('"status":"PENDING_RESPONSES"', result.content)
        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager.libraries), libraries_before)
        self.assertEqual(set(self.manager._agents_by_id), agents_before)

    async def test_invocation_guard_fails_instead_of_waiting_on_its_dependency(self):
        async with self.manager.agent_invocation(self.caller):
            with self.assertRaises(AgentInvocationDependencyError):
                async with self.manager.agent_invocation(self.caller):
                    self.fail("A dependent invocation must not start.")

    async def test_detached_task_ignores_completed_inherited_dependency(self):
        release = asyncio.Event()

        async def delayed_invocation():
            await release.wait()
            async with self.manager.agent_invocation(self.caller):
                return "completed"

        async with self.manager.agent_invocation(self.caller):
            task = asyncio.create_task(delayed_invocation())
        release.set()

        self.assertEqual(await task, "completed")

    async def test_idle_agent_receives_an_asynchronous_invitation(self):
        peer = Agent("IdlePeer", "Reviewer", self.client)
        self.manager.register_agent(peer)
        discussion = AsyncMock(return_value="completed")

        async with self.manager.agent_invocation(self.caller):
            with patch.object(
                self.manager,
                "execute_team_discussion",
                discussion,
            ):
                result = await self._dispatch_with_existing(peer.agent_id)

        self.assertIs(result.status, ToolResultStatus.SUCCESS)
        self.assertIn('"status":"PENDING_RESPONSES"', result.content)
        discussion.assert_not_awaited()
        self.assertTrue(
            any(
                message.message_type == "team_formation_invitation"
                for message in self.manager.list_agent_inbox(peer.agent_id)
            )
        )

    async def test_cancellation_after_agent_lock_acquisition_releases_lifecycle_state(self):
        agent_lock_acquired = asyncio.Event()
        finish_guard_entry = asyncio.Event()
        original_guard = self.caller.invocation_guard

        @asynccontextmanager
        async def signaling_guard():
            async with original_guard():
                agent_lock_acquired.set()
                await finish_guard_entry.wait()
                yield

        async def invoke():
            async with self.manager.agent_invocation(self.caller):
                self.fail("A cancelled invocation must not reach its body.")

        with patch.object(self.caller, "invocation_guard", signaling_guard):
            task = asyncio.create_task(invoke())
            await agent_lock_acquired.wait()
            await self.manager._runtime_gate.acquire()
            self.assertTrue(self.caller.lock.locked())
            finish_guard_entry.set()
            await asyncio.sleep(0)
            task.cancel()
            self.manager._runtime_gate.release()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                if self.manager._runtime_gate.locked():
                    self.manager._runtime_gate.release()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        self.assertFalse(self.caller.lock.locked())
        self.assertEqual(self.manager._starting_invocations, 0)
        self.assertEqual(self.manager._active_invocations, 0)
        self.assertFalse(self.manager._active_agent_invocation_tokens)

    async def test_cross_task_reciprocal_agent_wait_is_rejected_without_deadlock(self):
        barrier = asyncio.Barrier(2)

        async def invoke(source, target):
            async with self.manager.agent_invocation(source):
                await barrier.wait()
                async with self.manager.agent_invocation(target):
                    return "completed"

        results = await asyncio.wait_for(
            asyncio.gather(
                invoke(self.caller, self.ancestor),
                invoke(self.ancestor, self.caller),
                return_exceptions=True,
            ),
            timeout=5,
        )

        self.assertEqual(results.count("completed"), 1)
        failures = [
            result
            for result in results
            if isinstance(result, AgentInvocationDependencyError)
        ]
        self.assertEqual(len(failures), 1)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertFalse(self.caller.lock.locked())
        self.assertFalse(self.ancestor.lock.locked())

    async def test_longer_transitive_agent_wait_cycle_is_rejected(self):
        barrier = asyncio.Barrier(3)

        async def invoke(source, target):
            async with self.manager.agent_invocation(source):
                await barrier.wait()
                async with self.manager.agent_invocation(target):
                    return "completed"

        results = await asyncio.wait_for(
            asyncio.gather(
                invoke(self.caller, self.ancestor),
                invoke(self.ancestor, self.third),
                invoke(self.third, self.caller),
                return_exceptions=True,
            ),
            timeout=5,
        )

        self.assertEqual(results.count("completed"), 2)
        self.assertEqual(
            sum(
                isinstance(result, AgentInvocationDependencyError)
                for result in results
            ),
            1,
        )
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertFalse(self.caller.lock.locked())
        self.assertFalse(self.ancestor.lock.locked())
        self.assertFalse(self.third.lock.locked())

    async def test_wait_cycle_detection_is_not_limited_to_small_rings(self):
        agent_count = 12
        agents = [
            Agent(f"RingAgent{index}", "Reviewer", self.client)
            for index in range(agent_count)
        ]
        for agent in agents:
            self.manager.register_agent(agent)
        barrier = asyncio.Barrier(agent_count)

        async def invoke(index):
            source = agents[index]
            target = agents[(index + 1) % agent_count]
            async with self.manager.agent_invocation(source):
                await barrier.wait()
                async with self.manager.agent_invocation(target):
                    return "completed"

        results = await asyncio.wait_for(
            asyncio.gather(
                *(invoke(index) for index in range(agent_count)),
                return_exceptions=True,
            ),
            timeout=5,
        )

        self.assertEqual(results.count("completed"), agent_count - 1)
        self.assertEqual(
            sum(
                isinstance(result, AgentInvocationDependencyError)
                for result in results
            ),
            1,
        )
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertTrue(all(not agent.lock.locked() for agent in agents))

    async def test_admission_and_invocation_share_a_reference_counted_edge(self):
        edge = (self.caller.agent_id, self.ancestor.agent_id)

        async with self.manager.agent_invocation(self.caller):
            async with self.manager._lifecycle.reserve_synchronous_dependencies(
                (self.ancestor.agent_id,)
            ):
                self.assertEqual(self.manager._agent_wait_edge_counts[edge], 1)
                async with self.manager.agent_invocation(self.ancestor):
                    self.assertEqual(self.manager._agent_wait_edge_counts[edge], 2)
                self.assertEqual(self.manager._agent_wait_edge_counts[edge], 1)

        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_multi_agent_dependency_batch_is_all_or_nothing(self):
        existing_edge = (self.ancestor.agent_id, self.caller.agent_id)
        safe_candidate = (self.caller.agent_id, self.third.agent_id)
        cyclic_candidate = (self.caller.agent_id, self.ancestor.agent_id)

        async with self.manager._runtime_gate:
            reserved = self.manager._lifecycle._reserve_wait_edges_locked(
                existing_edge[0],
                (existing_edge[1],),
            )
            try:
                with self.assertRaises(AgentInvocationDependencyError):
                    self.manager._lifecycle._reserve_wait_edges_locked(
                        self.caller.agent_id,
                        (self.third.agent_id, self.ancestor.agent_id),
                    )
                self.assertNotIn(safe_candidate, self.manager._agent_wait_edge_counts)
                self.assertNotIn(cyclic_candidate, self.manager._agent_wait_edge_counts)
                self.assertEqual(self.manager._agent_wait_edge_counts, {existing_edge: 1})
            finally:
                self.manager._lifecycle._release_wait_edges_locked(reserved)

        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_dependency_reservation_is_released_when_cancelled(self):
        reservation_entered = asyncio.Event()
        hold_reservation = asyncio.Event()

        async def reserve_dependency():
            async with self.manager._lifecycle.reserve_synchronous_dependencies(
                (self.ancestor.agent_id,)
            ):
                reservation_entered.set()
                await hold_reservation.wait()

        async with self.manager.agent_invocation(self.caller):
            task = asyncio.create_task(reserve_dependency())
            await reservation_entered.wait()
            self.assertTrue(self.manager._agent_wait_edge_counts)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_reciprocal_sibling_invitations_create_no_synchronous_wait_cycle(self):
        barrier = asyncio.Barrier(2)
        alice_client = CoordinatedDelegatingClient(barrier)
        bob_client = CoordinatedDelegatingClient(barrier)
        self.manager.register_llm_client("alice-delegator", alice_client)
        self.manager.register_llm_client("bob-delegator", bob_client)
        alice = Agent("Alice", "Reviewer", alice_client)
        bob = Agent("Bob", "Reviewer", bob_client)
        self.manager.register_agent(alice)
        self.manager.register_agent(bob)
        alice_client.target_agent_id = bob.agent_id
        bob_client.target_agent_id = alice.agent_id
        team = self.manager.bootstrap_agent_team(
            self.manager.root_ai,
            existing_members=[alice, bob],
            member_configs={"Observer": {}},
        )
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        agents_before = set(self.manager._agents_by_id)
        managed_root = Path(self.tmpdir) / ".att_doc_libs"
        directories_before = {path.name for path in managed_root.iterdir()}

        result = await asyncio.wait_for(
            self.manager.execute_team_discussion_detailed(
                team,
                "Delegate a review and report back.",
                rounds=1,
                skip_audit=True,
            ),
            timeout=5,
        )

        self.assertEqual(result.status.value, "completed")
        self.assertEqual(len(team.child_teams), 0)
        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager._agents_by_id), agents_before)
        self.assertEqual(len(self.manager._formations.requests), 2)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertEqual(
            {request.status.value for request in self.manager._formations.requests.values()},
            {"collecting_responses"},
        )
        self.assertEqual(set(self.manager.libraries), libraries_before)
        self.assertEqual({path.name for path in managed_root.iterdir()}, directories_before)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertEqual(self.manager._starting_invocations, 0)
        self.assertEqual(self.manager._active_invocations, 0)
        self.assertFalse(alice.lock.locked())
        self.assertFalse(bob.lock.locked())
