"""Optional candidates retain actual personal provenance without inferring parents."""

import asyncio
import copy
from pathlib import Path
from unittest.mock import patch

from ai_team_team import StateRestoreError, TeamFormationDraftCandidate
from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle, personal_control_contract


class FormationArtifactSourceTests(ActivityTestCase):
    async def test_rejected_candidate_commit_cannot_leave_a_ready_artifact(self):
        candidate = TeamFormationDraftCandidate.model_validate_json('''{
            "member_count": 3, "preset_name": "custom", "system_instructions": "Own design.",
            "team_purpose": "Optional personal proposal", "member_configs": {"NewA": {}, "NewB": {}},
            "is_public_visible": false, "initiator_joins": true,
            "unanimous_acceptance_action": "require_confirmation", "late_join_policy": "disabled"
        }''')
        for failure in (StateRestoreError("Rejected artifact"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(self.manager, "_commit_dirty_state", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        await self.manager.prepare_team_formation_draft(actor=self.root,
                            objective="Reject this unaccepted artifact.", candidate=candidate)
                self.assertFalse(self.manager._formations.drafts)

    async def prepare_in_team(self):
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"PeerA": {}, "PeerB": {}})
        captured = []
        candidate = TeamFormationDraftCandidate.model_validate_json('''{
            "member_count": 3, "preset_name": "custom", "system_instructions": "Own design.",
            "team_purpose": "Optional personal proposal", "member_configs": {"NewA": {}, "NewB": {}},
            "is_public_visible": false, "initiator_joins": true,
            "unanimous_acceptance_action": "require_confirmation", "late_join_policy": "disabled"
        }''')

        async def prepare():
            captured.append(await self.manager.prepare_team_formation_draft(actor=self.root,
                objective="Prepare my own supplied candidate.", candidate=candidate))
            return {"draft_id": captured[-1].draft_id}

        self.manager.register_tool("prepare_fixture_candidate", func=prepare,
            execution_contract=personal_control_contract())
        self.steps(call("prepare_fixture_candidate"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id))
        await self.wait(admission)
        self.assertEqual(len(captured), 1)
        return team, captured[0]

    async def test_candidate_does_not_infer_parent_from_creator_or_scope(self):
        team, draft = await self.prepare_in_team()
        self.assertEqual(draft.creator_team_id, team.team_id)
        self.assertIsNone(draft.parent_team_id)
        self.assertIsNone(draft.parent_agent_id)
        self.assertIsNotNone(draft.initiator_invocation_id)
        source = self.manager._records.index[("activity_invocations", (draft.initiator_invocation_id,))]
        self.assertEqual(source.values["agent_id"], self.root.agent_id)
        self.assertEqual(source.values["scope_team_id"], team.team_id)
        self.assertEqual(len(self.client.requests), 2)

    async def test_first_partial_export_preserves_candidate_source_and_rejects_corruption(self):
        _team, draft = await self.prepare_in_team()
        dirty = self.manager._new_dirty_state()
        dirty["configs"] = True
        dirty["formation_drafts"].add(draft.draft_id)
        snapshot = self.manager._capture_state_snapshot(dirty)
        path = str(Path(self.workspace.name) / "candidate-only.sqlite")
        await asyncio.wrap_future(self.manager._persistence.submit(path, snapshot))
        state = await self.manager._persistence.read(path)
        self.manager._validate_state_snapshot(state)
        self.assertTrue(any(row.table_name == "activity_invocations" and
            row.values["invocation_id"] == draft.initiator_invocation_id for row in state["records"]))
        for field, value in (("initiator_invocation_id", "INVOCATION-missing"),
                ("source_message_id", "MESSAGE-missing")):
            corrupt = copy.deepcopy(state)
            corrupt["formation_drafts"][0][field] = value
            with self.subTest(field=field), self.assertRaises(StateRestoreError):
                self.manager._validate_state_snapshot(corrupt)
        self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root), draft)
