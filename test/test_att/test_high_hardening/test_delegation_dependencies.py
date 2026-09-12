import asyncio
import shutil
import tempfile
import unittest
from contextlib import asynccontextmanager
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
        return "Final Answer: done"

    def supports_native_tool_calling(self):
        return False


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

    async def test_direct_self_dependency_is_rejected_before_team_creation(self):
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        agents_before = set(self.manager._agents_by_id)

        async with self.manager.agent_invocation(self.caller):
            result = await self._dispatch_with_existing(self.caller.agent_id)

        self.assertIs(result.status, ToolResultStatus.BUSINESS_ERROR)
        self.assertEqual(result.error_kind, "agent_invocation_dependency")
        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager.libraries), libraries_before)
        self.assertEqual(set(self.manager._agents_by_id), agents_before)

    async def test_ancestor_dependency_is_rejected_before_team_creation(self):
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        agents_before = set(self.manager._agents_by_id)

        async with self.manager.agent_invocation(self.ancestor):
            async with self.manager.agent_invocation(self.caller):
                result = await self._dispatch_with_existing(
                    self.ancestor.agent_id
                )

        self.assertIs(result.status, ToolResultStatus.BUSINESS_ERROR)
        self.assertEqual(result.error_kind, "agent_invocation_dependency")
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

    async def test_idle_agent_can_still_join_a_synchronous_child(self):
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
        self.assertEqual(result.content, "completed")
        child = discussion.await_args.args[0]
        self.assertIn(peer, child.members)

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
