"""Depth limits survive optional artifacts, consent waits, and publication waits."""

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.core.exceptions import ToolBusinessError
from ai_team_team.core.formation import FormationDraftStatus, TeamFormationDraftCandidate
from ai_team_team.core.response import ToolResultStatus
from test.governance_client import approve_pending_business
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from ._lock_support import ObservedLock


class FormationCreationLimitTests(ActivityTestCase):
    def setup_parent(self):
        self.parent = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"ParentHelper1": {}, "ParentHelper2": {}})
        self.tools = self.manager.get_available_tools(self.parent, self.root)
        self.candidate = TeamFormationDraftCandidate.model_validate_json(json.dumps({
            "member_count": 3, "preset_name": "custom", "system_instructions": "", "team_purpose": "Depth-safe formation",
            "is_public_visible": False, "initiator_joins": True, "unanimous_acceptance_action": "require_confirmation",
            "late_join_policy": "disabled", "member_configs": {"ChildHelper1": {}, "ChildHelper2": {}}}))

    @contextmanager
    def as_initiator(self):
        actor_token = self.manager._active_tool_agent.set(self.root)
        team_token = self.manager._active_team.set(self.parent)
        try:
            yield
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(actor_token)

    async def invoke(self, name, **arguments):
        with self.as_initiator():
            return await self.tools[name].func(**arguments)

    async def prepare(self):
        return await self.invoke("prepare_team_formation_draft", objective="Prepare a voluntary child organization.",
            candidate=self.candidate, organizational_parent="current_team")

    async def publish(self, draft):
        return json.loads(await self.invoke("publish_team_formation_draft", draft_id=draft["draft_id"]))

    def workspace_entries(self):
        return set((Path(self.workspace.name) / ".att_doc_libs").rglob("*"))

    async def test_direct_and_optional_draft_entries_reject_an_overdepth_parent(self):
        self.setup_parent()
        self.manager.config.max_delegation_depth = 1
        before = self.workspace_entries()
        with self.assertRaisesRegex(ToolBusinessError, "depth"):
            await self.invoke("propose_team_formation", proposal=self.candidate, organizational_parent="current_team")
        with self.assertRaisesRegex(ToolBusinessError, "depth"):
            await self.prepare()
        self.assertFalse(self.manager._formations.drafts)
        self.assertFalse(self.manager._formations.requests)
        self.assertEqual(self.workspace_entries(), before)

    async def test_repeated_depth_denials_do_not_become_argument_health_faults(self):
        self.setup_parent()
        self.manager.config.max_delegation_depth = 1
        arguments = {"objective": "A valid candidate under the current organizational policy.",
            "candidate": self.candidate.model_dump(mode="json"), "organizational_parent": "current_team"}
        self.steps(*(call("prepare_team_formation_draft", arguments, call_id=f"candidate-{index}") for index in range(5)), idle())
        admission = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=self.parent.team_id))
        await self.wait(admission)
        self.assertFalse(self.records("health_incidents"))
        self.assertFalse(self.records("audit_runs"))
        self.assertFalse([row for row in self.records("health_observations") if row.values["detector"] == "tool_arguments"
            and not row.values["valid"]])
        denied = [job for job in self.manager._executions.jobs.values() if job.tool.name == "prepare_team_formation_draft"]
        self.assertEqual(len(denied), 5)
        self.assertTrue(all(job.result.status is ToolResultStatus.BUSINESS_ERROR for job in denied))

    async def test_draft_publication_rechecks_a_lowered_limit(self):
        self.setup_parent()
        draft = await self.prepare()
        self.manager.config.max_delegation_depth = 1
        with self.assertRaisesRegex(ToolBusinessError, "depth"):
            await self.publish(draft)
        self.assertEqual(self.manager._formations.drafts[draft["draft_id"]].status, FormationDraftStatus.READY)
        self.assertFalse(self.manager._formations.requests)

    async def test_confirmed_creation_rechecks_the_live_limit_and_remains_retryable(self):
        self.setup_parent()
        with patch.object(self.manager._activity, "schedule_notice"):
            published = await self.publish(await self.prepare())
            before = self.workspace_entries()
            self.manager.config.max_delegation_depth = 1
            with self.assertRaisesRegex(ToolBusinessError, "depth"):
                await self.invoke("create_team_from_formation", request_id=published["request_id"], proposal_revision=1)
            self.assertEqual(len(self.manager.teams), 1)
            self.assertEqual(self.workspace_entries(), before)
            self.manager.config.max_delegation_depth = 2
            created = json.loads(await self.invoke("create_team_from_formation",
                request_id=published["request_id"], proposal_revision=1))
        self.assertEqual(self.manager.teams[created["team_id"]].depth, 2)

    async def test_parent_migration_changes_the_depth_used_by_an_unpublished_candidate(self):
        self.setup_parent()
        draft = await self.prepare()
        target = self.manager.create_agent_team(self.root)
        with patch.object(self.manager._activity, "schedule_notice"):
            migration = await self.manager.negotiate_and_execute_migration(self.parent, target, "Attach before publishing the candidate.")
            await approve_pending_business(self.manager, migration.request_id)
        self.assertEqual(self.parent.depth, 2)
        with self.assertRaisesRegex(ToolBusinessError, "depth"):
            await self.publish(draft)
        self.assertFalse(self.manager._formations.requests)

    async def test_staged_creation_revalidates_before_registry_and_directory_publication(self):
        self.setup_parent()
        before = self.workspace_entries()
        teams, agents, libraries = set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)
        original = self.manager._create_agent_team

        def staged(*args, **kwargs):
            candidate = original(*args, **kwargs)
            self.manager.config.max_delegation_depth = 1
            return candidate

        with patch.object(self.manager, "_create_agent_team", side_effect=staged):
            with self.assertRaisesRegex(ValueError, "depth"):
                self.manager.create_agent_team(self.root, parent=self.parent)
        self.assertEqual(set(self.manager.teams), teams)
        self.assertEqual(set(self.manager._agents_by_id), agents)
        self.assertEqual(set(self.manager.libraries), libraries)
        self.assertEqual(self.workspace_entries(), before)

    async def assert_creation_receipt_rechecks_depth(self, *, durable):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        self.setup_parent()
        with patch.object(self.manager._activity, "schedule_notice"):
            published = await self.publish(await self.prepare())
            before = self.workspace_entries()
            teams, agents, libraries = set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)

            async def create():
                with self.as_initiator():
                    # The public wrapper owns only operation accounting. Exercise
                    # the same finalizer while another operation owns its gate.
                    return await self.manager._formations.create_team_from_formation(
                        published["request_id"], actor=self.root, proposal_revision=1)

            gate = ObservedLock(self.manager._runtime_gate)
            with patch.object(self.manager, "_runtime_gate", gate):
                async with gate:
                    pending = asyncio.create_task(create())
                    await gate.wait_for_attempt(pending)
                    self.assertTrue(any(getattr(team, "_publication_pending", False) for team in self.manager.teams.values()))
                    self.manager.config.max_delegation_depth = 1
                with self.assertRaisesRegex(ValueError, "depth"):
                    await pending
        self.assertEqual(set(self.manager.teams), teams)
        self.assertEqual(set(self.manager._agents_by_id), agents)
        self.assertEqual(set(self.manager.libraries), libraries)
        self.assertEqual(self.workspace_entries(), before)

    async def test_volatile_creation_receipt_rechecks_the_limit_after_its_wait(self):
        await self.assert_creation_receipt_rechecks_depth(durable=False)

    async def test_durable_creation_receipt_rechecks_the_limit_after_its_wait(self):
        await self.assert_creation_receipt_rechecks_depth(durable=True)

    async def test_automatic_creation_rechecks_a_limit_changed_after_proposal(self):
        self.setup_parent()
        automatic = self.candidate.model_copy(update={"unanimous_acceptance_action":
            type(self.candidate.unanimous_acceptance_action).AUTO_CREATE})
        with patch.object(self.manager._activity, "schedule_notice"):
            proposed = await self.invoke("propose_team_formation", proposal=automatic, organizational_parent="current_team")
            self.manager.config.max_delegation_depth = 1
            while self.manager._formations.tasks:
                await asyncio.gather(*tuple(self.manager._formations.tasks))
                await asyncio.sleep(0)
        self.assertEqual(len(self.manager.teams), 1)
        request = self.manager._formations.requests[proposed["request"]["request_id"]]
        self.assertIsNone(request.created_team_id)
        self.assertIn("depth", request.decision_reason)

    async def test_independent_and_agent_parent_choices_are_not_blocked_by_current_team_depth(self):
        self.setup_parent()
        self.manager.config.max_delegation_depth = 1
        with patch.object(self.manager._activity, "schedule_notice"):
            for choice in ("none", "self"):
                proposed = await self.invoke("propose_team_formation", proposal=self.candidate, organizational_parent=choice)
                created = json.loads(await self.invoke("create_team_from_formation",
                    request_id=proposed["request"]["request_id"], proposal_revision=1))
                self.assertEqual(self.manager.teams[created["team_id"]].depth, 1)
