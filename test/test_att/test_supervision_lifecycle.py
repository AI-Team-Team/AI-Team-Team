"""Fresh managed audit people, exact profiles, and receipt-owned teardown."""

import asyncio
import copy
import os
import sqlite3
from contextlib import closing
from unittest.mock import patch

from ai_team_team import ATTConfig, Agent, AuditStatus, HealthSubject, LLMResponse, StatePersistenceError, ToolCall
from ai_team_team.core.activity.contracts import AgentTeamScope
from test.async_waits import wait_for_runtime
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class ScopedHealthClient(HealthModelClient):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.seen = {}
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.pause = False

    async def generate(self, *args, **kwargs):
        team = self.manager._active_team.get()
        if team is not None and team.team_kind == "supervisory":
            self.seen.setdefault(team.team_id, set()).update(member.agent_id for member in team.members)
            if self.pause:
                self.entered.set()
                await self.release.wait()
        return await super().generate(*args, **kwargs)


class TestSupervisoryTeamLifecycle(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.health = ScopedHealthClient(self.manager)
        self.manager.register_llm_client("audit", self.health)
        self.root.llm_client = self.health
        self.team = self.manager.create_agent_team(self.root)

    def subject(self, team=None):
        return HealthSubject(kind="agent_team", subject_id=(team or self.team).team_id)

    async def admit(self, team=None, marker="Permitted metadata"):
        return await self.manager.request_health_assessment(self.subject(team), {"kind": "host", "facts": [marker]})

    def ordinary_identities(self):
        return set(self.manager._agents_by_id), set(self.manager.teams), set(self.manager.libraries)

    def assert_no_auditors(self):
        self.assertFalse(any(team.team_kind == "supervisory" for team in self.manager.teams.values()))
        self.assertFalse(self.manager.supervisor.profiles)

    async def test_each_audit_is_a_new_registered_team_and_disposes_its_people(self):
        before = self.ordinary_identities()
        for marker in ("First permitted signal", "Second permitted signal"):
            admission = await self.admit(marker=marker)
            result = await self.manager.wait_for_health_assessment(admission.audit_id)
            self.assertEqual(result.status, AuditStatus.HEALTHY)
            self.assertEqual(self.ordinary_identities(), before)
        self.assertEqual(len(self.health.seen), 2)
        first, second = self.health.seen.values()
        self.assertFalse(first & second)
        self.assertEqual(len(self.records("audit_evidence")), 2)
        self.assert_no_auditors()

    async def test_temporary_factory_does_not_publish_ordinary_identity_state(self):
        with patch.object(self.manager, "_auto_save", side_effect=AssertionError("Unexpected ordinary save")):
            team = self.manager._team_creation.create_supervisory_team()
        self.assertIs(self.manager.teams[team.team_id], team)
        await self.manager._team_creation.dissolve_supervisory_team(team, persist=False)

    async def test_parallel_audits_have_separate_live_owners_and_provider_context(self):
        self.health.pause = True
        other = self.manager.create_agent_team(self.root)
        first, second = await asyncio.gather(self.admit(marker="ALPHA_SIGNAL"), self.admit(other, "BETA_SIGNAL"))
        try:
            async with asyncio.timeout(10):
                while len(self.health.seen) < 2:
                    await asyncio.sleep(0)
            live = [team for team in self.manager.teams.values() if team.team_kind == "supervisory"]
            self.assertEqual(len(live), 2)
            self.assertFalse({person.agent_id for person in live[0].members} & {person.agent_id for person in live[1].members})
            topology = self.manager.render_topology_tree()
            for team in live:
                self.assertNotIn(team.team_id, topology)
                self.assertEqual(self.manager.get_available_tools(team), {})
                for person in team.members:
                    self.assertIs(self.manager._agents_by_id[person.agent_id], person)
                    with self.assertRaises(ValueError):
                        self.manager._resolve_existing_team_members([person], None)
            self.assertIsNone(self.manager._active_team.get())
            self.assertIsNone(self.manager._active_tool_agent.get())
        finally:
            self.health.release.set()
        results = await asyncio.gather(self.manager.wait_for_health_assessment(first.audit_id), self.manager.wait_for_health_assessment(second.audit_id))
        self.assertTrue(all(result.status == AuditStatus.HEALTHY for result in results))
        self.assert_no_auditors()

    async def test_parallel_personal_activities_and_audits_keep_separate_contexts(self):
        manager = self.manager
        manager.config.activity.max_concurrent_activities = 8
        manager.config.activity.max_concurrent_model_requests = 8

        class ConcurrentClient(HealthModelClient):
            def __init__(inner):
                super().__init__()
                inner.ordinary_ready, inner.audits_ready = asyncio.Event(), asyncio.Event()
                inner.release_ordinary, inner.release_audits = asyncio.Event(), asyncio.Event()
                inner.ordinary_owners, inner.audit_owners = set(), set()
                inner.frames, inner.contexts = {}, {}

            async def generate(inner, prompt, system_instruction=None, tools=None, **kwargs):
                team = manager._active_team.get()
                if team is None:
                    raise AssertionError("The provider lost its invocation-scoped AgentTeam.")
                owners = [person.agent_id for person in team.members if person.agent_id in system_instruction]
                if len(owners) != 1:
                    raise AssertionError("The provider instructions do not identify exactly one caller.")
                owner = owners[0]
                inner.frames.setdefault(owner, []).append((copy.deepcopy(prompt), system_instruction))

                def sample_context():
                    scope = manager._active_team.get()
                    inner.contexts.setdefault(owner, []).append((
                        scope.team_id if scope else None, manager._active_tool_agent.get(), manager._activity.current.get()))

                sample_context()
                if team.team_kind == "ordinary":
                    inner.ordinary_owners.add(owner)
                    if len(inner.ordinary_owners) == 2:
                        inner.ordinary_ready.set()
                    await inner.release_ordinary.wait()
                else:
                    called = {call["function"]["name"] for message in prompt for call in message.get("tool_calls", ())}
                    if "read_audit_evidence" not in called:
                        return LLMResponse(tool_calls=[ToolCall("read-evidence", "read_audit_evidence", {})])
                    if "submit_health_finding" not in called:
                        inner.audit_owners.add(owner)
                        if len(inner.audit_owners) == 6:
                            inner.audits_ready.set()
                        await inner.release_audits.wait()
                sample_context()
                return await super().generate(prompt, system_instruction, tools, **kwargs)

        client = ConcurrentClient()
        manager.register_llm_client("isolation", client)
        self.root.llm_client = client
        people = [manager.register_agent(Agent(f"Worker{label}", "Researcher", client,
            system_instructions=f"ORDINARY_{label}_PRIVATE_CONTEXT")) for label in ("ALPHA", "BETA")]
        teams = [manager.bootstrap_agent_team(self.root, existing_members=[person],
            member_configs={f"{label}HelperA": {}, f"{label}HelperB": {}})
            for label, person in zip(("Alpha", "Beta"), people)]
        before = self.ordinary_identities()
        admissions = await asyncio.gather(*(manager.activate_agent(person.agent_id,
            scope=AgentTeamScope(team_id=team.team_id)) for person, team in zip(people, teams)))
        try:
            await wait_for_runtime(manager, client.ordinary_ready.wait(), label="Two ordinary providers are live")
            audits = await asyncio.gather(*(self.admit(team, f"HEALTH_{label}_EVIDENCE")
                for team, label in zip(teams, ("ALPHA", "BETA"))))
            await wait_for_runtime(manager, client.audits_ready.wait(), label="Both audit electorates read their own evidence")
            live = [team for team in manager.teams.values() if team.team_kind == "supervisory"]
            self.assertEqual(len(live), 2)
            self.assertEqual(len(client.audit_owners), 6)
            self.assertTrue(all(manager.inspect_agent_activity(person.agent_id).intent == "continuing" for person in people))
            self.assertTrue(all(not manager._activity.models.live[person.agent_id].done() for person in people))
            self.assertIsNone(manager._active_team.get())
            self.assertIsNone(manager._active_tool_agent.get())
            client.release_audits.set()
            results = await wait_for_runtime(manager, asyncio.gather(*(manager.wait_for_health_assessment(audit.audit_id)
                for audit in audits)), label="Parallel audits finish while ordinary providers wait")
            self.assertTrue(all(result.status is AuditStatus.HEALTHY for result in results))
            self.assert_no_auditors()
            self.assertEqual(self.ordinary_identities(), before)
            self.assertTrue(all(not manager._activity.models.live[person.agent_id].done() for person in people))
        finally:
            client.release_audits.set()
            client.release_ordinary.set()
            await asyncio.gather(*(self.wait(admission) for admission in admissions))
            await self.settle()

        for index, (person, team) in enumerate(zip(people, teams)):
            own, other = ("ALPHA", "BETA") if index == 0 else ("BETA", "ALPHA")
            frame = repr(client.frames[person.agent_id])
            self.assertIn(f"ORDINARY_{own}_PRIVATE_CONTEXT", frame)
            self.assertNotIn(f"ORDINARY_{other}_PRIVATE_CONTEXT", frame)
            self.assertNotIn("HEALTH_ALPHA_EVIDENCE", frame)
            self.assertNotIn("HEALTH_BETA_EVIDENCE", frame)
            remembered = repr((person.messages, person.message_history))
            self.assertNotIn("HEALTH_ALPHA_EVIDENCE", remembered)
            self.assertNotIn("HEALTH_BETA_EVIDENCE", remembered)
            self.assertEqual(client.contexts[person.agent_id], [(team.team_id, None, None)] * 2)
        runs = {row.values["audit_id"]: row for row in self.records("audit_runs")}
        checkpoints = self.records("audit_activity_checkpoints")
        for index, audit in enumerate(audits):
            own, other = ("ALPHA", "BETA") if index == 0 else ("BETA", "ALPHA")
            run = runs[audit.audit_id]
            for owner in run.values["electorate"]:
                frames = repr(client.frames[owner])
                self.assertIn(f"HEALTH_{own}_EVIDENCE", frames)
                self.assertNotIn(f"HEALTH_{other}_EVIDENCE", frames)
                self.assertNotIn("ORDINARY_ALPHA_PRIVATE_CONTEXT", frames)
                self.assertNotIn("ORDINARY_BETA_PRIVATE_CONTEXT", frames)
                self.assertTrue(all(context == (run.values["temporary_team_id"], None, None)
                    for context in client.contexts[owner]))
            retained = repr([row.values["working_context"] for row in checkpoints if row.values["audit_id"] == audit.audit_id])
            self.assertIn(f"HEALTH_{own}_EVIDENCE", retained)
            self.assertNotIn(f"HEALTH_{other}_EVIDENCE", retained)
            self.assertNotIn("ORDINARY_ALPHA_PRIVATE_CONTEXT", retained)
            self.assertNotIn("ORDINARY_BETA_PRIVATE_CONTEXT", retained)

    async def test_live_snapshot_contains_evidence_but_no_temporary_identity_or_files(self):
        path = os.path.join(self.workspace.name, "live.sqlite")
        self.manager.db_path = path
        await self.manager.save_state()
        self.health.pause = True
        admission = await self.admit()
        await asyncio.wait_for(self.health.entered.wait(), 10)
        live = next(team for team in self.manager.teams.values() if team.team_kind == "supervisory")
        temporary_ids = [person.agent_id for person in live.members]
        try:
            await self.manager.save_state()
            with closing(sqlite3.connect(path)) as database:
                self.assertEqual(database.execute("SELECT COUNT(*) FROM teams WHERE team_id=?", (live.team_id,)).fetchone()[0], 0)
                for owner in temporary_ids:
                    self.assertEqual(database.execute("SELECT COUNT(*) FROM agents WHERE agent_id=?", (owner,)).fetchone()[0], 0)
                    self.assertEqual(database.execute("SELECT COUNT(*) FROM libraries WHERE owner_agent_id=?", (owner,)).fetchone()[0], 0)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM audit_participants").fetchone()[0], 3)
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            self.health.release.set()
        await self.manager.wait_for_health_assessment(admission.audit_id)

    async def test_evidence_survives_restore_without_reviving_auditors(self):
        admission = await self.admit()
        await self.manager.wait_for_health_assessment(admission.audit_id)
        path = os.path.join(self.workspace.name, "completed.sqlite")
        await self.manager.save_state(path)
        before = len(self.health.calls)
        await self.manager.load_state(path)
        self.assert_no_auditors()
        self.assertEqual(len(self.health.calls), before)
        result = await self.manager.wait_for_health_assessment(admission.audit_id)
        self.assertEqual(result.status, AuditStatus.HEALTHY)
        self.assertEqual(len(self.records("audit_findings")), 3)

    async def test_failed_factory_teardown_restores_registered_people_and_directories(self):
        team = self.manager._team_creation.create_supervisory_team()
        roots = [self.manager.libraries[owner].root_dir for owner in [f"DL-{team.team_id}", *[person.private_doc_library_id for person in team.members]]]
        with patch.object(self.manager, "_commit_dirty_state", side_effect=StatePersistenceError("Rejected teardown")):
            with self.assertRaises(StatePersistenceError):
                await self.manager._team_creation.dissolve_supervisory_team(team)
        self.assertIs(self.manager.teams[team.team_id], team)
        self.assertTrue(all(os.path.isdir(root) for root in roots))
        await self.manager._team_creation.dissolve_supervisory_team(team, persist=False)

    async def test_names_stay_reserved_until_teardown_settles(self):
        team = self.manager._team_creation.create_supervisory_team()
        person = team.members[0]
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._commit_dirty_state

        async def hold(dirty):
            entered.set()
            await release.wait()
            return await original(dirty)

        with patch.object(self.manager, "_commit_dirty_state", hold):
            task = asyncio.create_task(self.manager._team_creation.dissolve_supervisory_team(team))
            try:
                await entered.wait()
                with self.assertRaises(ValueError):
                    self.manager.register_agent(Agent(person.name, "Duplicate", self.health))
            finally:
                release.set()
            await task
        self.assertNotIn(person.name, self.manager.agents)

    async def test_full_save_cannot_resurrect_a_team_during_teardown(self):
        path = os.path.join(self.workspace.name, "save-race.sqlite")
        self.manager.db_path = path
        await self.manager.save_state()
        team = self.manager._team_creation.create_supervisory_team()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._commit_dirty_state

        async def hold(dirty):
            entered.set()
            await release.wait()
            return await original(dirty)

        with patch.object(self.manager, "_commit_dirty_state", hold):
            teardown = asyncio.create_task(self.manager._team_creation.dissolve_supervisory_team(team))
            await entered.wait()
            save = asyncio.create_task(self.manager.save_state())
            await asyncio.sleep(0)
            self.assertFalse(save.done())
            release.set()
            await asyncio.gather(teardown, save)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM teams WHERE team_id=?", (team.team_id,)).fetchone()[0], 0)

    async def test_repeated_cancellation_does_not_undo_receipt_owned_teardown(self):
        team = self.manager._team_creation.create_supervisory_team()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._commit_dirty_state

        async def hold(dirty):
            entered.set()
            await release.wait()
            return await original(dirty)

        with patch.object(self.manager, "_commit_dirty_state", hold):
            task = asyncio.create_task(self.manager._team_creation.dissolve_supervisory_team(team))
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertNotIn(team.team_id, self.manager.teams)

    async def test_cancelling_an_observer_does_not_cancel_its_accepted_audit(self):
        self.health.pause = True
        admission = await self.admit()
        await self.health.entered.wait()
        observer = asyncio.create_task(self.manager.wait_for_health_assessment(admission.audit_id))
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertTrue(self.manager.supervisor.profiles)
        self.health.release.set()
        self.assertEqual((await self.manager.wait_for_health_assessment(admission.audit_id)).status, AuditStatus.HEALTHY)

    async def test_explicit_cancellation_retains_unknown_and_dissolves_the_team(self):
        self.health.pause = True
        admission = await self.admit()
        await self.health.entered.wait()
        await self.manager.cancel_health_assessment(admission.audit_id)
        self.assert_no_auditors()
        result = await self.manager.wait_for_health_assessment(admission.audit_id)
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertEqual(self.records("audit_evidence")[0].values["findings"]["failure_kind"], "CancelledError")

    async def test_initial_persistence_failure_never_leaves_privileged_people(self):
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("Admission rejected")):
            with self.assertRaises(StatePersistenceError):
                await self.admit()
        self.assert_no_auditors()

    async def test_evidence_failure_is_propagated_but_does_not_retain_privilege(self):
        original = self.manager._records.commit

        async def fail_evidence(records, **kwargs):
            if any(row.table_name == "audit_evidence" for row in records):
                raise StatePersistenceError("Evidence write rejected")
            return await original(records, **kwargs)

        with patch.object(self.manager._records, "commit", fail_evidence):
            admission = await self.admit()
            with self.assertRaises(StatePersistenceError):
                await self.manager.wait_for_health_assessment(admission.audit_id)
        self.assert_no_auditors()

    async def test_close_finishes_durable_unknown_and_removes_live_privilege(self):
        self.health.pause = True
        admission = await self.admit()
        await self.health.entered.wait()
        await asyncio.wait_for(self.manager.close(), 10)
        self.assert_no_auditors()
        self.assertFalse(self.manager.supervisor.finalizers)
        self.assertEqual((await self.manager.wait_for_health_assessment(admission.audit_id)).status, AuditStatus.UNKNOWN)
