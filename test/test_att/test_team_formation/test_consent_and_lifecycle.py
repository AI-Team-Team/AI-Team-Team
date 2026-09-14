import asyncio
import json
import shutil
import tempfile
import unittest

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    InvitationAttitude,
    TeamFormationInspection,
    TeamFormationRequest,
    TeamFormationStatus,
)
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.core.exceptions import ToolPermissionError
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, require_json=False, **kwargs):
        if require_json:
            return json.dumps({"is_healthy": True, "reason": "Synthetic audit."})
        return "Final Answer: completed"

    def supports_native_tool_calling(self):
        return False


class TestConsensualTeamFormation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-formation-")
        self.client = EchoClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
        )
        self.manager.register_llm_client("echo", self.client)
        self.invitees = [
            Agent(f"Invitee{index}", "Researcher", self.client)
            for index in range(1, 5)
        ]
        for invitee in self.invitees:
            self.manager.register_agent(invitee)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _identity_snapshot(agent):
        return {
            "name": agent.name,
            "role": agent.role,
            "role_description": agent.role_description,
            "system_instructions": agent.system_instructions,
            "llm_client": agent.llm_client,
            "messages": list(agent.messages),
            "message_history": list(agent.message_history),
            "last_context": agent.last_context,
            "lifecycle_state": agent.lifecycle_state,
            "private_doc_library_id": agent.private_doc_library_id,
            "lock": agent.lock,
        }

    def _proposal(self, **overrides):
        arguments = {
            "creator": self.root,
            "member_configs": {
                "NewAnalyst": {"model": "echo"},
                "NewReviewer": {"model": "echo"},
            },
            "existing_members": self.invitees,
            "team_purpose": "Consent-sensitive research",
        }
        arguments.update(overrides)
        return self.manager.create_agent_team(**arguments)

    async def test_ordinary_api_only_opens_invitations_and_preserves_agent_identity(self):
        before_teams = set(self.manager.teams)
        before_libraries = set(self.manager.libraries)
        identity_before = {
            agent.agent_id: self._identity_snapshot(agent)
            for agent in self.invitees
        }

        request = self._proposal()

        self.assertIsInstance(request, TeamFormationRequest)
        self.assertEqual(set(self.manager.teams), before_teams)
        self.assertEqual(set(self.manager.libraries), before_libraries)
        self.assertEqual(request.status, TeamFormationStatus.COLLECTING_RESPONSES)
        self.assertEqual(
            {
                message.message_type
                for agent in self.invitees
                for message in self.manager.list_agent_inbox(agent.agent_id)
            },
            {"team_formation_invitation"},
        )
        inspection = self.manager.inspect_team_formation(
            request.request_id,
            actor=self.invitees[0],
        )
        self.assertIsInstance(inspection, TeamFormationInspection)
        self.assertEqual(inspection.request.team_purpose, "Consent-sensitive research")
        self.assertEqual(inspection.summary.no_response, 4)
        self.assertFalse(inspection.summary.can_create)
        for agent in self.invitees:
            self.assertEqual(self._identity_snapshot(agent), identity_before[agent.agent_id])

    async def test_four_attitudes_are_visible_but_only_acceptance_joins(self):
        request = self._proposal()
        initiator_messages = len(self.manager.list_agent_inbox(self.root.agent_id))
        unchanged = await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[3],
            attitude=None,
        )
        self.assertIn("explicitly chose", unchanged.reason)
        decisions = self.manager.list_team_formation_decisions(request.request_id)
        self.assertEqual(decisions[-1].attitude, InvitationAttitude.NO_RESPONSE)
        self.assertEqual(
            len(self.manager.list_agent_inbox(self.root.agent_id)),
            initiator_messages,
        )

        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[1],
            attitude="declined",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[2],
            attitude="explicitly_ignored",
        )
        inspection = self.manager.inspect_team_formation(
            request.request_id,
            actor=self.root,
        )
        self.assertEqual(
            (
                inspection.summary.accepted,
                inspection.summary.declined,
                inspection.summary.explicitly_ignored,
                inspection.summary.no_response,
            ),
            (1, 1, 1, 1),
        )
        self.assertTrue(inspection.summary.can_create)

        result = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        team = self.manager.teams[result.team_id]
        self.assertIn(self.invitees[0], team.members)
        self.assertNotIn(self.root, team.members)
        for invitee in self.invitees[1:]:
            self.assertNotIn(invitee, team.members)

    async def test_unanimous_auto_creation_and_confirmation_abandonment(self):
        auto_request = self.manager.create_agent_team(
            self.root,
            existing_members=self.invitees[:3],
            unanimous_acceptance_action="auto_create",
        )
        for invitee in self.invitees[:2]:
            result = await self.manager.respond_team_invitation(
                auto_request.request_id,
                proposal_revision=auto_request.proposal_revision,
                actor=invitee,
                attitude="accepted",
            )
            self.assertEqual(result.status, "INVITATION_UPDATED")
        result = await self.manager.respond_team_invitation(
            auto_request.request_id,
            proposal_revision=auto_request.proposal_revision,
            actor=self.invitees[2],
            attitude="accepted",
        )
        self.assertEqual(result.status, "CREATED")
        self.assertEqual(
            set(self.manager.teams[result.team_id].members),
            set(self.invitees[:3]),
        )

        confirmation = self.manager.create_agent_team(
            self.root,
            existing_members=self.invitees[:3],
            unanimous_acceptance_action="require_confirmation",
        )
        for invitee in self.invitees[:3]:
            result = await self.manager.respond_team_invitation(
                confirmation.request_id,
                proposal_revision=confirmation.proposal_revision,
                actor=invitee,
                attitude="accepted",
            )
        self.assertEqual(result.status, "READY_FOR_CONFIRMATION")
        abandoned = await self.manager.abandon_team_formation(
            confirmation.request_id,
            proposal_revision=confirmation.proposal_revision,
            actor=self.root,
            reason="The initiating Agent changed its plan.",
        )
        self.assertEqual(abandoned.status, "ABANDONED")
        for invitee in self.invitees[:3]:
            self.assertTrue(
                any(
                    message.message_type == "team_formation_abandoned"
                    and message.payload["request_id"] == confirmation.request_id
                    for message in self.manager.list_agent_inbox(invitee.agent_id)
                )
            )

    async def test_late_join_is_always_invitee_initiated(self):
        request = self._proposal(
            existing_members=self.invitees[:2],
            late_join_policy="open",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        team = self.manager.teams[created.team_id]
        self.assertNotIn(self.invitees[1], team.members)
        joined = await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[1],
            attitude="accepted",
        )
        self.assertEqual(joined.status, "JOINED")
        self.assertIn(self.invitees[1], team.members)

        confirmed_request = self._proposal(
            existing_members=self.invitees[2:],
            late_join_policy="require_initiator_confirmation",
        )
        await self.manager.respond_team_invitation(
            confirmed_request.request_id,
            proposal_revision=confirmed_request.proposal_revision,
            actor=self.invitees[2],
            attitude="accepted",
        )
        confirmed_created = await self.manager.create_team_from_formation(
            confirmed_request.request_id,
            proposal_revision=confirmed_request.proposal_revision,
            actor=self.root,
        )
        confirmed_team = self.manager.teams[confirmed_created.team_id]
        pending = await self.manager.respond_team_invitation(
            confirmed_request.request_id,
            proposal_revision=confirmed_request.proposal_revision,
            actor=self.invitees[3],
            attitude="accepted",
        )
        self.assertEqual(pending.status, "LATE_JOIN_PENDING")
        self.assertNotIn(self.invitees[3], confirmed_team.members)
        approved = await self.manager.decide_team_formation_late_join(
            confirmed_request.request_id,
            self.invitees[3].agent_id,
            proposal_revision=confirmed_request.proposal_revision,
            actor=self.root,
            approved=True,
        )
        self.assertEqual(approved.status, "JOINED")
        self.assertIn(self.invitees[3], confirmed_team.members)

    async def test_membership_boolean_controls_are_strict(self):
        with self.assertRaisesRegex(TypeError, "initiator_joins must be a boolean"):
            self.manager.create_agent_team(
                self.root,
                existing_members=self.invitees[:3],
                initiator_joins="false",
            )
        self.assertFalse(self.manager._formations.requests)

        request = self._proposal(
            existing_members=self.invitees[:2],
            late_join_policy="require_initiator_confirmation",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        pending = await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[1],
            attitude="accepted",
        )
        self.assertEqual(pending.status, "LATE_JOIN_PENDING")
        with self.assertRaisesRegex(TypeError, "approved must be a boolean"):
            await self.manager.decide_team_formation_late_join(
                request.request_id,
                self.invitees[1].agent_id,
                proposal_revision=request.proposal_revision,
                actor=self.root,
                approved="false",
            )
        self.assertNotIn(self.invitees[1], self.manager.teams[created.team_id].members)

    async def test_failed_open_late_join_restores_attitude_membership_and_inboxes(self):
        request = self._proposal(
            existing_members=self.invitees[:2],
            late_join_policy="open",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        team = self.manager.teams[created.team_id]
        late_invitee = self.invitees[1]
        initiator_inbox = [dict(message) for message in self.root.agent_inbox]
        invitee_inbox = [dict(message) for message in late_invitee.agent_inbox]
        original_commit = self.manager._commit_dirty_state

        async def fail_commit(_dirty):
            raise RuntimeError("Injected late-join persistence failure.")

        self.manager._commit_dirty_state = fail_commit
        try:
            with self.assertRaisesRegex(RuntimeError, "late-join persistence"):
                await self.manager.respond_team_invitation(
                    request.request_id,
                    proposal_revision=request.proposal_revision,
                    actor=late_invitee,
                    attitude="accepted",
                )
        finally:
            self.manager._commit_dirty_state = original_commit
        self.assertNotIn(late_invitee, team.members)
        invitation = self.manager.get_team_formation_invitation(
            request.request_id,
            late_invitee.agent_id,
        )
        self.assertEqual(invitation.attitude, InvitationAttitude.NO_RESPONSE)
        self.assertIsNone(invitation.responded_at)
        self.assertEqual(self.root.agent_inbox, initiator_inbox)
        self.assertEqual(late_invitee.agent_inbox, invitee_inbox)

    async def test_notification_failure_rolls_back_invitation_decision_and_late_join_state(self):
        request = self._proposal(existing_members=self.invitees[:1])
        invitee = self.invitees[0]
        original_notify = self.manager._formations._notify_agent
        original_inboxes = {
            agent.agent_id: [dict(message) for message in agent.agent_inbox]
            for agent in (self.root, invitee)
        }
        original_decisions = set(self.manager._formations.decisions)

        def fail_notify(*_args, **_kwargs):
            raise RuntimeError("Injected formation notification failure.")

        self.manager._formations._notify_agent = fail_notify
        try:
            with self.assertRaisesRegex(RuntimeError, "notification failure"):
                await self.manager.respond_team_invitation(
                    request.request_id,
                    proposal_revision=request.proposal_revision,
                    actor=invitee,
                    attitude="declined",
                )
        finally:
            self.manager._formations._notify_agent = original_notify

        invitation = self.manager.get_team_formation_invitation(
            request.request_id,
            invitee.agent_id,
        )
        self.assertEqual(invitation.attitude, InvitationAttitude.NO_RESPONSE)
        self.assertEqual(set(self.manager._formations.decisions), original_decisions)
        for agent in (self.root, invitee):
            self.assertEqual(agent.agent_inbox, original_inboxes[agent.agent_id])

        late_request = self._proposal(
            existing_members=self.invitees[:2],
            late_join_policy="require_initiator_confirmation",
        )
        await self.manager.respond_team_invitation(
            late_request.request_id,
            proposal_revision=late_request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        await self.manager.create_team_from_formation(
            late_request.request_id,
            proposal_revision=late_request.proposal_revision,
            actor=self.root,
        )
        late_invitee = self.invitees[1]
        original_decisions = set(self.manager._formations.decisions)
        original_inboxes = {
            agent.agent_id: [dict(message) for message in agent.agent_inbox]
            for agent in (self.root, late_invitee)
        }
        self.manager._formations._notify_agent = fail_notify
        try:
            with self.assertRaisesRegex(RuntimeError, "notification failure"):
                await self.manager.respond_team_invitation(
                    late_request.request_id,
                    proposal_revision=late_request.proposal_revision,
                    actor=late_invitee,
                    attitude="accepted",
                )
        finally:
            self.manager._formations._notify_agent = original_notify

        invitation = self.manager.get_team_formation_invitation(
            late_request.request_id,
            late_invitee.agent_id,
        )
        self.assertEqual(invitation.attitude, InvitationAttitude.NO_RESPONSE)
        self.assertFalse(invitation.late_join_pending)
        self.assertEqual(set(self.manager._formations.decisions), original_decisions)
        for agent in (self.root, late_invitee):
            self.assertEqual(agent.agent_inbox, original_inboxes[agent.agent_id])

    async def test_late_join_revalidates_agent_lifecycle_after_waiting_for_team_lock(self):
        late_invitee = self.invitees[0]
        request = self._proposal(
            existing_members=[late_invitee],
            member_configs={
                "NewAnalyst": {},
                "NewReviewer": {},
                "NewVerifier": {},
            },
            late_join_policy="open",
        )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        team = self.manager.teams[created.team_id]
        await team.state_lock.acquire()
        late_join = asyncio.create_task(
            self.manager.respond_team_invitation(
                request.request_id,
                proposal_revision=request.proposal_revision,
                actor=late_invitee,
                attitude="accepted",
            )
        )
        try:
            for _ in range(100):
                invitation = self.manager.get_team_formation_invitation(
                    request.request_id,
                    late_invitee.agent_id,
                )
                if invitation.attitude is InvitationAttitude.ACCEPTED:
                    break
                await asyncio.sleep(0)
            else:
                self.fail("The late-join operation did not reach the team lock.")
            await self.manager.retire_agent(late_invitee.agent_id, policy="retain")
        finally:
            team.state_lock.release()
        with self.assertRaisesRegex(PermissionError, "active and registered"):
            await late_join
        self.assertNotIn(late_invitee, team.members)
        invitation = self.manager.get_team_formation_invitation(
            request.request_id,
            late_invitee.agent_id,
        )
        self.assertEqual(invitation.attitude, InvitationAttitude.NO_RESPONSE)
        self.assertIsNone(invitation.responded_at)

    async def test_cancelled_late_join_wait_restores_uncommitted_invitation_state(self):
        late_invitee = self.invitees[0]
        request = self._proposal(
            existing_members=[late_invitee],
            member_configs={
                "NewAnalyst": {},
                "NewReviewer": {},
                "NewVerifier": {},
            },
            late_join_policy="open",
        )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.root,
        )
        team = self.manager.teams[created.team_id]
        await team.state_lock.acquire()
        late_join = asyncio.create_task(
            self.manager.respond_team_invitation(
                request.request_id,
                proposal_revision=request.proposal_revision,
                actor=late_invitee,
                attitude="accepted",
            )
        )
        try:
            for _ in range(100):
                invitation = self.manager.get_team_formation_invitation(
                    request.request_id,
                    late_invitee.agent_id,
                )
                if invitation.attitude is InvitationAttitude.ACCEPTED:
                    break
                await asyncio.sleep(0)
            else:
                self.fail("The late-join operation did not reach the team lock.")
            self.assertIn(late_join, self.manager._formation_operation_tasks)
            late_join.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await late_join
        finally:
            team.state_lock.release()
        self.assertNotIn(late_invitee, team.members)
        invitation = self.manager.get_team_formation_invitation(
            request.request_id,
            late_invitee.agent_id,
        )
        self.assertEqual(invitation.attitude, InvitationAttitude.NO_RESPONSE)
        self.assertIsNone(invitation.responded_at)
        self.assertNotIn(late_join, self.manager._formation_operation_tasks)

    async def test_agent_tool_cannot_override_the_acting_identity(self):
        request = self._proposal(existing_members=self.invitees[:1])
        tool = get_default_tools(self.manager.tools_context, self.invitees[0])[
            "respond_team_invitation"
        ]
        with self.assertRaisesRegex(
            ToolPermissionError,
            "active Agent invocation",
        ):
            await tool.invoke(
                request_id=request.request_id,
                proposal_revision=request.proposal_revision,
                attitude="accepted",
            )
        executor = ToolExecutor(None, self.invitees[0], self.manager)
        result = await executor.execute(
            "respond_team_invitation",
            kwargs={
                "request_id": request.request_id,
                "proposal_revision": request.proposal_revision,
                "attitude": "accepted",
            },
            tools={"respond_team_invitation": tool},
        )
        self.assertEqual(result.status.value, "success")
        self.assertEqual(
            self.manager.get_team_formation_invitation(
                request.request_id,
                self.invitees[0].agent_id,
            ).attitude,
            InvitationAttitude.ACCEPTED,
        )
        self.assertNotIn("acting_agent_id", tool.json_schema["properties"])
        self.assertIn("None", tool.description)
        self.assertIn("externally indistinguishable", tool.description)

    async def test_shared_agent_launch_uses_the_invocation_team_without_ambiguity(self):
        shared = self.invitees[0]
        first_parent = self.manager.bootstrap_agent_team(
            self.root,
            member_configs={"FirstPeer": {}, "FirstReviewer": {}},
            existing_members=[shared],
        )
        second_parent = self.manager.bootstrap_agent_team(
            self.root,
            member_configs={"SecondPeer": {}, "SecondReviewer": {}},
            existing_members=[shared],
        )
        agent_token = self.manager._active_tool_agent.set(shared)
        team_token = self.manager._active_team.set(second_parent)
        try:
            request = shared.launch_att(
                self.manager,
                member_configs={"NewAnalyst": {}, "NewReviewer": {}},
                existing_members=[self.invitees[1]],
            )
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        self.assertIsInstance(request, TeamFormationRequest)
        self.assertEqual(request.parent_team_id, second_parent.team_id)
        self.assertNotEqual(request.parent_team_id, first_parent.team_id)

    async def test_inspection_requires_the_registered_active_agent_instance(self):
        request = self._proposal(existing_members=self.invitees[:1])
        invitee = self.invitees[0]
        forged = Agent(
            "ForgedInvitee",
            "Researcher",
            self.client,
            agent_id=invitee.agent_id,
        )
        with self.assertRaisesRegex(PermissionError, "active and registered"):
            self.manager.inspect_team_formation(
                request.request_id,
                actor=forged,
            )

    async def test_concurrent_finalization_creates_at_most_one_team(self):
        request = self.manager.create_agent_team(
            self.root,
            existing_members=self.invitees[:3],
        )
        for invitee in self.invitees[:3]:
            await self.manager.respond_team_invitation(
                request.request_id,
                proposal_revision=request.proposal_revision,
                actor=invitee,
                attitude="accepted",
            )
        teams_before = set(self.manager.teams)
        results = await asyncio.gather(
            self.manager.create_team_from_formation(
                request.request_id,
                actor=self.root,
                proposal_revision=request.proposal_revision,
            ),
            self.manager.create_team_from_formation(
                request.request_id,
                actor=self.root,
                proposal_revision=request.proposal_revision,
            ),
        )
        self.assertEqual({result.team_id for result in results}, {results[0].team_id})
        self.assertEqual(len(set(self.manager.teams) - teams_before), 1)

    async def test_creation_summary_revalidates_live_agent_eligibility(self):
        request = self._proposal(existing_members=self.invitees[:1])
        invitee = self.invitees[0]
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=invitee,
            attitude="accepted",
        )
        self.assertTrue(
            self.manager.inspect_team_formation(
                request.request_id,
                actor=self.root,
            ).summary.can_create
        )

        await self.manager.retire_agent(invitee.agent_id, policy="retain")

        summary = self.manager.inspect_team_formation(
            request.request_id,
            actor=self.root,
        ).summary
        self.assertFalse(summary.can_create)
        self.assertIn("active", summary.eligibility_reason)
        with self.assertRaisesRegex(ValueError, "active"):
            await self.manager.create_team_from_formation(
                request.request_id,
                proposal_revision=request.proposal_revision,
                actor=self.root,
            )

    async def test_failed_eligibility_reason_commit_restores_request_metadata(self):
        request = self._proposal(existing_members=self.invitees[:1])
        original_reason = request.decision_reason
        original_updated_at = request.updated_at
        original_commit = self.manager._commit_dirty_state

        async def fail_commit(_dirty):
            raise OSError("Injected eligibility-reason persistence failure.")

        self.manager._commit_dirty_state = fail_commit
        try:
            with self.assertRaisesRegex(OSError, "eligibility-reason"):
                await self.manager.create_team_from_formation(
                    request.request_id,
                    proposal_revision=request.proposal_revision,
                    actor=self.root,
                )
        finally:
            self.manager._commit_dirty_state = original_commit

        self.assertEqual(request.decision_reason, original_reason)
        self.assertEqual(request.updated_at, original_updated_at)

    async def test_commit_revalidates_initiator_membership_after_staging(self):
        parent = self.manager.create_agent_team(self.root)
        initiator = parent.members[0]
        request = self.manager.create_agent_team(
            parent,
            member_configs={"NewAnalyst": {}, "NewReviewer": {}},
            existing_members=[self.invitees[0]],
            initiating_agent=initiator,
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            proposal_revision=request.proposal_revision,
            actor=self.invitees[0],
            attitude="accepted",
        )
        teams_before = set(self.manager.teams)
        libraries_before = set(self.manager.libraries)
        original_staging = self.manager._team_creation._create_agent_team

        def remove_initiator_after_staging(*args, **kwargs):
            stage = original_staging(*args, **kwargs)
            parent.members.remove(initiator)
            return stage

        self.manager._team_creation._create_agent_team = remove_initiator_after_staging
        try:
            with self.assertRaisesRegex(ValueError, "left the creating AgentTeam"):
                await self.manager.create_team_from_formation(
                    request.request_id,
                    proposal_revision=request.proposal_revision,
                    actor=initiator,
                )
        finally:
            self.manager._team_creation._create_agent_team = original_staging
            parent.members.append(initiator)
        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager.libraries), libraries_before)
