"""A formal proposal requires live creator authority after admission waits."""

import asyncio
import json
from unittest.mock import patch

from ai_team_team import TeamFormationDraftCandidate, TeamFormationRevisionPatch
from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class FormationPublicationAuthorityTests(ActivityTestCase):
    async def assert_departed_initiator_cannot_publish(self, *, durable, action, agent_creator=False):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        parent = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"ParentA": {}, "ParentB": {}, "ParentC": {}})
        request = None
        if action != "initial_draft":
            request = self.manager.propose_team_formation(creator=self.root if agent_creator else parent,
                initiating_agent=self.root, initiator_joins=True, member_configs={"NewA": {}, "NewB": {}},
                team_purpose="Original proposal", parent=parent)
        draft = None
        if action != "revision":
            candidate = TeamFormationDraftCandidate.model_validate_json(json.dumps({
                "member_count": 3, "preset_name": "custom", "system_instructions": "Own design.",
                "team_purpose": "Successor proposal", "member_configs": {"NewA": {}, "NewB": {}},
                "is_public_visible": False, "initiator_joins": True,
                "unanimous_acceptance_action": "require_confirmation", "late_join_policy": "disabled"}))
            token = self.manager._active_team.set(None if agent_creator else parent)
            try:
                draft = await self.manager.prepare_team_formation_draft(actor=self.root,
                    objective="Publish only with live creator authority.", candidate=candidate,
                    request_id=request.request_id if request else None, parent=None if request else parent)
            finally:
                self.manager._active_team.reset(token)
        async def publish():
            if action == "revision":
                return await self.manager.revise_team_formation(request.request_id, actor=self.root,
                    base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="Unauthorized successor"))
            return await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with activity:
                removal = asyncio.create_task(self.manager._messaging.replace_members(parent,
                    [member for member in parent.members if member is not self.root], actor=self.root))
                await activity.wait_for_attempt(removal)
                publication = asyncio.create_task(publish())
                await activity.wait_for_attempt(publication)
            await removal
            with self.assertRaisesRegex(PermissionError, "no longer a member"):
                await publication
        self.assertNotIn(self.root, parent.members)
        if request:
            self.assertEqual(self.manager.get_team_formation(request.request_id), request)
        else:
            self.assertFalse(self.manager._formations.requests)
        if draft:
            self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "ready")
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        if durable:
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertEqual(len(state["formation_requests"]), int(request is not None))

    async def test_volatile_initial_publication_rechecks_creator_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=False, action="initial_draft")

    async def test_durable_initial_publication_rechecks_creator_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=True, action="initial_draft")

    async def test_agent_creator_publication_rechecks_intended_parent_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=False, action="initial_draft", agent_creator=True)

    async def test_revision_rechecks_creator_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=False, action="revision")

    async def test_durable_revision_rechecks_creator_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=True, action="revision")

    async def test_revision_draft_rechecks_creator_membership(self):
        await self.assert_departed_initiator_cannot_publish(durable=False, action="revision_draft")

    async def assert_membership_rechecked_after_preparation(self, *, unchanged):
        parent = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"ParentA": {}, "ParentB": {}, "ParentC": {}})
        candidate = TeamFormationDraftCandidate.model_validate_json(json.dumps({
            "member_count": 3, "preset_name": "custom", "system_instructions": "",
            "team_purpose": "Original proposal", "member_configs": {"NewA": {}, "NewB": {}},
            "is_public_visible": False, "initiator_joins": True,
            "unanimous_acceptance_action": "require_confirmation", "late_join_policy": "disabled"}))
        request = self.manager.propose_team_formation(creator=parent, initiating_agent=self.root,
            initiator_joins=True, member_configs={"NewA": {}, "NewB": {}}, team_purpose="Original proposal", parent=parent)
        draft = None
        if unchanged:
            draft = await self.manager.prepare_team_formation_draft(actor=self.root, objective="Same candidate.",
                candidate=candidate, request_id=request.request_id)
        runtime = ObservedLock(self.manager._runtime_gate)
        records = ObservedLock(self.manager._records.lock)
        async def publish():
            if unchanged:
                return await self.manager._formations.publish_team_formation_draft(draft.draft_id, actor=self.root)
            return await self.manager._formations.prepare_team_formation_draft(actor=self.root, objective="Validate only current authority.",
                candidate=candidate, request_id=request.request_id)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager, "_runtime_gate", runtime), \
                patch.object(self.manager._records, "lock", records):
            async with records:
                removal = asyncio.create_task(self.manager._messaging.replace_members(parent,
                    [member for member in parent.members if member is not self.root], actor=self.root))
                await records.wait_for_attempt(removal)
                publication = asyncio.create_task(publish())
                await runtime.wait_for_attempt(publication)
            await removal
            with self.assertRaisesRegex(PermissionError, "no longer a member"):
                await publication
        self.assertEqual(self.manager.get_team_formation(request.request_id), request)
        if unchanged:
            self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "ready")
        else:
            self.assertFalse(self.manager._formations.drafts)

    async def test_unchanged_draft_publication_rechecks_creator_authority(self):
        await self.assert_membership_rechecked_after_preparation(unchanged=True)

    async def test_candidate_preparation_rechecks_creator_authority(self):
        await self.assert_membership_rechecked_after_preparation(unchanged=False)
