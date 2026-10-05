import asyncio
import tempfile
import unittest

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    ApprovalPrincipal,
    ParentApprovalCommunicationConfig,
)
from test.governance_client import PersonalGovernanceClient


class GovernanceRoundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-governance-rounds-")
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
        async with asyncio.timeout(10):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)

    async def setup_round(self):
        parent = self.manager.create_agent_team(self.root)
        sender = self.manager.create_agent_team(parent)
        recipient = self.manager.create_agent_team(parent)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Public request."
        )
        await self.manager.execute_team_discussion(
            parent, "Discuss the public request.", rounds=1, skip_audit=True
        )
        await self.settle()
        return (
            parent,
            self.manager.broker.communication_requests[result.request_id],
            next(iter(self.manager._governance.rounds.values())),
        )

    async def choose(self, actor, item, approved):
        token = self.manager._active_tool_agent.set(actor)
        try:
            return await self.manager.submit_governance_choice(
                item.round_id, {"approved": approved, "reason": actor.name}, actor=actor
            )
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_complete_electorate_required_and_session_released(self):
        team, request, item = await self.setup_round()
        self.assertFalse(team.discussion_lock.locked())
        for actor in team.members[:2]:
            await self.choose(actor, item, True)
        await self.settle()
        self.assertEqual(item.status, "PENDING")
        self.assertEqual(request.status.value, "PENDING")
        await self.manager.mark_agent_inbox_read(team.members[2].agent_id)
        self.assertEqual(item.status, "PENDING")
        await self.choose(team.members[2], item, False)
        await self.settle()
        self.assertEqual(item.status, "APPROVED")
        self.assertEqual(request.status.value, "APPROVED")
        self.assertTrue(all(len(actor.agent_inbox) == 1 for actor in team.members))

    async def test_membership_changes_supersede_instead_of_reusing_votes(self):
        team, request, item = await self.setup_round()
        await self.choose(team.members[0], item, True)
        removed = team.members[-1]
        replacement = Agent("Replacement", "Same person", self.client)
        self.manager.register_agent(replacement)
        async with team.state_lock:
            team.members[-1] = replacement
        result = await self.choose(team.members[1], item, True)
        self.assertEqual(result.status, "CLOSED")
        self.assertEqual(item.status, "SUPERSEDED")
        await self.manager.execute_team_discussion(
            team, "Renewed deliberation.", rounds=1, skip_audit=True
        )
        await self.settle()
        current = self.manager._governance.latest(
            "communication", request.request_id, item.principal
        )
        self.assertEqual(current.round_number, 2)
        self.assertEqual(len(item.ballots), 1)
        self.assertNotIn(removed.agent_id, current.voter_agent_ids)
        self.assertFalse(current.ballots)

    async def test_tie_creates_new_round_without_deleting_history(self):
        team, request, item = await self.setup_round()
        async with team.state_lock:
            team.members.pop()
        # Changing the frozen electorate starts another explicit round.
        await self.manager.execute_team_discussion(
            team, "Two-person decision.", rounds=1, skip_audit=True
        )
        await self.settle()
        current = self.manager._governance.latest(
            "communication", request.request_id, item.principal
        )
        await self.choose(team.members[0], current, True)
        await self.choose(team.members[1], current, False)
        self.assertEqual(current.status, "TIED")
        await self.manager.execute_team_discussion(
            team, "Another public deliberation.", rounds=1, skip_audit=True
        )
        await self.settle()
        renewed = self.manager._governance.latest(
            "communication", request.request_id, item.principal
        )
        self.assertEqual(renewed.round_number, current.round_number + 1)
        self.assertEqual(len(current.ballots), 2)
        self.assertFalse(renewed.ballots)
        self.assertEqual(request.status.value, "PENDING")

    async def test_shared_agent_uses_one_invocation_lock_and_continuous_history(self):
        shared = Agent("Shared", "Independent", self.client, system_instructions="My own mission.")
        self.manager.register_agent(shared)
        first = self.manager.bootstrap_agent_team(
            self.root,
            member_count=3,
            existing_members=[shared],
            roles_and_presets=[("One", "one"), ("Two", "two")],
        )
        second = self.manager.bootstrap_agent_team(
            self.root,
            member_count=3,
            existing_members=[shared],
            roles_and_presets=[("Three", "three"), ("Four", "four")],
        )
        active = 0
        maximum = 0

        async def generate(prompt=None, system_instruction=None, **kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            self.assertIn("My own mission.", system_instruction)
            await asyncio.sleep(0.02)
            active -= 1
            return "Final Answer: My deliberate public reply."

        self.client.generate = generate
        await asyncio.gather(
            self.manager.execute_agent_interaction(shared, "First team's activity.", team=first),
            self.manager.execute_agent_interaction(shared, "Second team's activity.", team=second),
        )
        self.assertEqual(maximum, 1)
        self.assertEqual(shared.system_instructions, "My own mission.")
        self.assertIn("First team's activity.", str(shared.message_history))
        self.assertIn("Second team's activity.", str(shared.message_history))
        self.assertEqual(
            {message.get("team_id") for message in shared.message_history},
            {first.team_id, second.team_id},
        )
