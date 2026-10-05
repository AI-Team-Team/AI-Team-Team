import asyncio
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    LLMResponse,
    ParentApprovalCommunicationConfig,
    StatePersistenceError,
    ToolCall,
)
from ai_team_team.core.decision import DecisionOutcome
from test.governance_client import PersonalGovernanceClient


class GovernanceReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-governance-review-")
        self.addCleanup(self.workspace.cleanup)
        self.client = PersonalGovernanceClient(respond=False)
        self.root = Agent("Root", "Root", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.workspace.name,
                enable_memory_compression=False,
                communication=ParentApprovalCommunicationConfig(),
            ),
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)

    async def settle(self):
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)

    async def request(self, parent=None):
        sender = self.manager.create_agent_team(parent or self.root)
        recipient = self.manager.create_agent_team(parent or self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Public review request."
        )
        if parent is not None:
            await self.manager.execute_team_discussion(
                parent, "Deliberate normally.", rounds=1, skip_audit=True
            )
        await self.settle()
        return self.manager.broker.communication_requests[result.request_id]

    async def choose(self, actor, item):
        token = self.manager._active_tool_agent.set(actor)
        try:
            await self.manager.submit_governance_choice(
                item.round_id, {"approved": True, "reason": actor.name}, actor=actor
            )
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_unrecognized_decision_cannot_authorize_a_channel(self):
        request = await self.request()
        principal = request.approval_principals[0]
        await self.manager.broker._claim_approval(request.request_id, principal)
        await self.manager.broker._complete_approval(
            request.request_id, principal, DecisionOutcome("unknown", "No valid decision.")
        )
        self.assertEqual(request.status.value, "PENDING")
        self.assertFalse(self.manager.broker.agreements)
        self.assertFalse(next(iter(self.manager._governance.rounds.values())).ballots)

    async def test_authoritative_projection_uses_the_accepted_round_ballots(self):
        parent = self.manager.create_agent_team(self.root)
        request = await self.request(parent)
        item = next(iter(self.manager._governance.rounds.values()))
        with patch.object(self.manager._governance, "schedule_resolution"):
            for actor in parent.members:
                await self.choose(actor, item)
        principal = request.approval_principals[0]
        await self.manager.broker._claim_approval(request.request_id, principal)
        await self.manager.broker._complete_approval(
            request.request_id,
            principal,
            DecisionOutcome("approved", "Incomplete external projection.", round_id=item.round_id),
        )
        self.assertEqual(request.status.value, "APPROVED")
        self.assertEqual(
            {ballot.voter_agent_id for ballot in self.manager.broker.ballots[request.request_id]},
            set(item.voter_agent_ids),
        )

    async def test_cancelled_native_submission_keeps_the_next_interaction_usable(self):
        self.client.native = True
        self.client.respond = True
        self.manager.config.tool_calling_mode = "native"
        committed = asyncio.Event()
        original_commit = self.manager._commit_dirty_state

        async def pause_after_ballot(dirty):
            await original_commit(dirty)
            if dirty["agents"] and dirty["governance_rounds"]:
                committed.set()
                await asyncio.Event().wait()

        with patch.object(self.manager, "_commit_dirty_state", side_effect=pause_after_ballot):
            sender = self.manager.create_agent_team(self.root)
            recipient = self.manager.create_agent_team(self.root)
            result = await self.manager.broker.request_peer_communication(
                sender, recipient, sender.members[0].agent_id, "A cancellable explicit choice."
            )
            await asyncio.wait_for(committed.wait(), timeout=3)
            notification = next(
                task
                for key, task in self.manager._governance.tasks.items()
                if key.startswith("mail:")
            )
            notification.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await notification
        await self.settle()
        self.assertEqual(
            self.manager.broker.communication_requests[result.request_id].status.value, "APPROVED"
        )
        self.client.respond = False
        generate = self.client.generate

        async def validate_protocol(prompt=None, **kwargs):
            pending = set()
            for message in prompt:
                if message.get("tool_calls"):
                    self.assertFalse(pending)
                    pending = {call["id"] for call in message["tool_calls"]}
                elif message["role"] == "tool":
                    self.assertIn(message["tool_call_id"], pending)
                    pending.remove(message["tool_call_id"])
                else:
                    self.assertFalse(pending, "Interrupted native calls must retain valid replies.")
            self.assertFalse(pending)
            return await generate(prompt=prompt, **kwargs)

        self.client.generate = validate_protocol
        turn = await self.manager.execute_agent_interaction(self.root, "Continue ordinary work.")
        self.assertEqual(turn.status.value, "completed")

    async def test_fatal_native_batch_settles_siblings_before_releasing_identity(self):
        self.client.native = True
        self.manager.config.tool_calling_mode = "native"
        entered = asyncio.Event()
        stopped = asyncio.Event()
        tasks = []

        async def generate(**kwargs):
            return LLMResponse(
                tool_calls=[
                    ToolCall(call_id="fatal", name="list_agent_inbox", arguments={}),
                    ToolCall(call_id="pending", name="list_private_files", arguments={}),
                ]
            )

        async def execute(tool_name, *, call_id, **kwargs):
            if call_id == "pending":
                tasks.append(asyncio.current_task())
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            await entered.wait()
            raise StatePersistenceError("An authoritative write failed.")

        self.client.generate = generate
        try:
            with patch("ai_team_team.core.strategies.native.ToolExecutor.execute", side_effect=execute):
                with self.assertRaises(StatePersistenceError):
                    await self.manager.execute_agent_interaction(self.root, "Run a native batch.")
            self.assertTrue(stopped.is_set())
            self.assertTrue(all(task.done() for task in tasks))
            self.assertFalse(self.root.lock.locked())
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_migration_cannot_start_during_restore_or_after_queued_shutdown(self):
        sender = self.manager.create_agent_team(self.root)
        target = self.manager.create_agent_team(self.root)
        self.manager._restore_in_progress = True
        try:
            with self.assertRaises(RuntimeError):
                await self.manager.negotiate_and_execute_migration(sender, target, "Concurrent restore.")
        finally:
            self.manager._restore_in_progress = False
        self.assertFalse(self.manager._migration.requests)

        await self.manager._migration.lock.acquire()
        task = asyncio.create_task(
            self.manager.negotiate_and_execute_migration(sender, target, "Queued before closing.")
        )
        await asyncio.sleep(0)
        self.manager._closing = True
        self.manager._migration.lock.release()
        try:
            with self.assertRaises(RuntimeError):
                await task
        finally:
            self.manager._closing = False
        self.assertFalse(self.manager._migration.requests)

    async def test_communication_cannot_start_during_restore_or_queued_shutdown(self):
        sender = self.manager.create_agent_team(self.root)
        recipient = self.manager.create_agent_team(self.root)
        self.manager._restore_in_progress = True
        try:
            with self.assertRaises(RuntimeError):
                await self.manager.broker.request_peer_communication(
                    sender, recipient, sender.members[0].agent_id, "Concurrent restore."
                )
        finally:
            self.manager._restore_in_progress = False
        self.assertFalse(self.manager.broker.communication_requests)

        await self.manager.broker._transaction_lock.acquire()
        task = asyncio.create_task(
            self.manager.broker.request_peer_communication(
                sender, recipient, sender.members[0].agent_id, "Queued before closing."
            )
        )
        await asyncio.sleep(0)
        self.manager._closing = True
        self.manager.broker._transaction_lock.release()
        try:
            with self.assertRaises(RuntimeError):
                await task
        finally:
            self.manager._closing = False
        self.assertFalse(self.manager.broker.communication_requests)

    async def test_pending_outcome_preserves_other_processing_principals(self):
        left = self.manager.create_agent_team(self.root)
        right = self.manager.create_agent_team(self.root)
        sender = self.manager.create_agent_team(left)
        recipient = self.manager.create_agent_team(right)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Two independent authorities."
        )
        request = self.manager.broker.communication_requests[result.request_id]
        first, second = request.approval_principals
        await self.manager.broker._claim_approval(request.request_id, first)
        await self.manager.broker._claim_approval(request.request_id, second)
        await self.manager.broker._complete_approval(
            request.request_id, first, DecisionOutcome("pending", "The email remains unanswered.")
        )
        self.assertEqual(request.status.value, "PROCESSING")
        await self.manager.broker._complete_approval(
            request.request_id, second, DecisionOutcome("pending", "Another unanswered email.")
        )
        self.assertEqual(request.status.value, "PENDING")

    async def test_migration_failure_restores_original_sibling_order(self):
        self.manager.config.migration_policy = "permissive"
        parent = self.manager.create_agent_team(self.root)
        target = self.manager.create_agent_team(self.root)
        moving = self.manager.create_agent_team(parent)
        self.manager.create_agent_team(parent)
        children = list(parent.child_teams)
        target_children = list(target.child_teams)
        original_commit = self.manager._commit_dirty_state

        async def fail_topology_commit(dirty):
            if dirty["teams"]:
                raise OSError("Topology persistence failed.")
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=fail_topology_commit):
            with self.assertRaises(OSError):
                await self.manager.negotiate_and_execute_migration(moving, target, "Move safely.")
        self.assertEqual(parent.child_teams, children)
        self.assertEqual(target.child_teams, target_children)
        self.assertIs(moving.parent_team, parent)
        self.assertEqual(moving.migration_count, 0)
