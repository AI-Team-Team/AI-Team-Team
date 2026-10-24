"""Volatile relationship facts survive normal mutations, batching, and export."""

import asyncio
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import Agent
from ai_team_team.core.manager.activity.values import ModelUnavailable
from ai_team_team.tool.membership import build_membership_tools
from test.governance_client import settle_governance_activity
from test.test_att.test_autonomous_activity_phase0._fixtures import AgentIdentitySnapshot

from ._support import hydrate_team_stream_id, invocation_graph, make_manager


def current_intervals(manager, team):
    return [row for row in manager._records.snapshot() if row.table_name == "membership_intervals"
            and row.values["team_id"] == team.team_id and row.values["leave_event_id"] is None]


class VolatileMembershipTests(unittest.IsolatedAsyncioTestCase):
    async def settle_resource_blocked_mail(self, manager):
        # These foundation tests exercise relationship facts without dispatching
        # model work. Addressed mail remains accepted and observably blocked.
        try:
            await settle_governance_activity(manager)
        except ModelUnavailable:
            pass

    def create_team(self, manager, creator=None, *, size=4):
        return manager.bootstrap_agent_team(creator or manager.root_ai, parent=creator or manager.root_ai, member_configs={
            f"Member-{index}": {"model": "fixture"} for index in range(size)
        })

    async def test_export_then_public_removal_keeps_unrelated_commits_valid(self):
        manager, path, client = make_manager(self, volatile=True)
        parent = self.create_team(manager, size=3)
        team = self.create_team(manager, parent)
        person = team.members[0]
        manager.libraries[person.private_doc_library_id].write_file("note.txt", "Personal fixture")
        identity = AgentIdentitySnapshot.capture(person, manager)
        hydrate_team_stream_id(manager, team, "opaque-team-stream")
        await manager.save_state(path)
        original = next(row for row in current_intervals(manager, team) if row.values["agent_id"] == person.agent_id)
        agent_token = manager._active_tool_agent.set(parent.members[0])
        team_token = manager._active_team.set(parent)
        try:
            await build_membership_tools(manager, parent)["remove_team_member"](team.team_id, person.name)
        finally:
            manager._active_team.reset(team_token)
            manager._active_tool_agent.reset(agent_token)
        self.assertEqual(AgentIdentitySnapshot.capture(person, manager), identity)
        self.assertIsNotNone(manager._records.index[original.identity].values["leave_event_id"])
        receipt = await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        self.assertEqual(receipt.durability, "volatile")
        self.assertIsNone(manager.db_path)
        await manager.save_state(path)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM team_members WHERE team_id=?", (team.team_id,)).fetchone(), (3,))
            self.assertEqual(database.execute("SELECT stream_id FROM chat_streams WHERE team_id=?", (team.team_id,)).fetchone(), ("opaque-team-stream",))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        await manager.load_state(path)
        self.assertEqual(len(manager.teams[team.team_id].members), 3)
        self.assertEqual(client.requests, [])

    async def test_creation_and_public_add_record_history_without_disk_io(self):
        manager, _, client = make_manager(self, volatile=True)
        parent = self.create_team(manager, size=3)
        team = self.create_team(manager, parent, size=3)
        identities = {member.agent_id: AgentIdentitySnapshot.capture(member, manager) for member in team.members}
        agent_token = manager._active_tool_agent.set(parent.members[0])
        team_token = manager._active_team.set(parent)
        try:
            await build_membership_tools(manager, parent)["add_team_member"](team.team_id, "Additional", "fixture", "", "")
        finally:
            manager._active_team.reset(team_token)
            manager._active_tool_agent.reset(agent_token)
        self.assertEqual({row.values["agent_id"] for row in current_intervals(manager, team)}, {member.agent_id for member in team.members})
        for member in team.members:
            if member.agent_id in identities:
                self.assertEqual(AgentIdentitySnapshot.capture(member, manager), identities[member.agent_id])
        self.assertEqual(manager._persistence._stores, {})
        self.assertEqual(manager._persistence._leases, {})
        self.assertIsNone(manager._persistence._active_task)
        self.assertEqual(client.requests, [])

    async def test_nested_suppression_preserves_leave_and_rejoin_as_distinct_intervals(self):
        manager, path, client = make_manager(self, volatile=True)
        team = self.create_team(manager)
        person = team.members[0]
        identity = AgentIdentitySnapshot.capture(person, manager)
        first = next(row for row in current_intervals(manager, team) if row.values["agent_id"] == person.agent_id)
        async with manager.suppress_auto_save():
            with manager._resources.mutation():
                team.members.remove(person)
            manager._auto_save(teams={team.team_id})
            self.assertIsNotNone(manager._records.index[first.identity].values["leave_event_id"])
            async with manager.suppress_auto_save():
                # Trusted fixture mutation exercises capture independently of
                # the invitation workflow, not an Agent-facing consent bypass.
                with manager._resources.mutation():
                    team.members.append(person)
                manager._auto_save(teams={team.team_id})
        second = next(row for row in current_intervals(manager, team) if row.values["agent_id"] == person.agent_id)
        self.assertNotEqual(second.identity, first.identity)
        self.assertEqual(AgentIdentitySnapshot.capture(person, manager), identity)
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        await manager.save_state(path)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM membership_intervals WHERE team_id=? AND agent_id=?", (team.team_id, person.agent_id)).fetchone(), (2,))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(client.requests, [])

    async def test_authoritative_local_delta_uses_the_same_relationship_producer(self):
        manager, _, client = make_manager(self, volatile=True)
        team = self.create_team(manager)
        person = team.members[0]
        with manager._resources.mutation():
            team.members.remove(person)
        dirty = manager._new_dirty_state()
        dirty["teams"].add(team.team_id)
        await manager._commit_dirty_state(dirty)
        self.assertNotIn(person.agent_id, {row.values["agent_id"] for row in current_intervals(manager, team)})
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        self.assertEqual(manager._persistence._stores, {})
        self.assertEqual(client.requests, [])

    async def test_consensual_creation_and_late_join_record_current_intervals(self):
        manager, _, client = make_manager(self, volatile=True)
        manager.config.model_token_limits["fixture"] = 0
        invitees = [manager.register_agent(Agent(f"Invitee-{index}", "Researcher", client)) for index in range(4)]
        request = manager.create_agent_team(manager.root_ai, parent=manager.root_ai, existing_members=invitees, late_join_policy="open")
        for person in invitees[:3]:
            await manager.respond_team_invitation(request.request_id, proposal_revision=request.proposal_revision, actor=person, attitude="accepted")
        created = await manager.create_team_from_formation(request.request_id, proposal_revision=request.proposal_revision, actor=manager.root_ai)
        team = manager.teams[created.team_id]
        self.assertEqual(len(current_intervals(manager, team)), 3)
        joined = await manager.respond_team_invitation(request.request_id, proposal_revision=request.proposal_revision, actor=invitees[3], attitude="accepted")
        self.assertEqual(joined.status, "JOINED")
        self.assertEqual({row.values["agent_id"] for row in current_intervals(manager, team)}, {person.agent_id for person in invitees})
        await self.settle_resource_blocked_mail(manager)
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        self.assertEqual(client.requests, [])

    async def test_short_lived_supervisory_teams_never_enter_ordinary_history(self):
        manager, _, client = make_manager(self, volatile=True)
        team = manager._team_creation.create_supervisory_team()
        self.assertEqual(manager._records.snapshot(), ())
        await manager._team_creation.dissolve_supervisory_team(team, persist=False)
        self.assertEqual(manager._records.snapshot(), ())
        self.assertEqual(client.requests, [])

    async def test_history_owner_cannot_be_deleted_but_can_be_archived(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, _, client = make_manager(self, volatile=volatile)
                team = self.create_team(manager)
                person = team.members[0]
                with manager._resources.mutation():
                    team.members.remove(person)
                manager._auto_save(teams={team.team_id})
                _ = person.lock, person.lifecycle_lock
                identity = AgentIdentitySnapshot.capture(person, manager)
                with self.assertRaisesRegex(ValueError, "durable history references"):
                    await manager.retire_agent(person.agent_id, "delete", confirm_delete=True)
                self.assertEqual(AgentIdentitySnapshot.capture(person, manager), identity)
                await manager.retire_agent(person.agent_id, "archive")
                await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
                self.assertEqual(person.lifecycle_state, "archived")
                self.assertEqual(client.requests, [])

    async def test_first_partial_checkpoint_includes_previously_captured_relationships(self):
        manager, path, client = make_manager(self, volatile=True)
        parent = self.create_team(manager, size=3)
        team = self.create_team(manager, parent, size=3)
        identities = {member.agent_id: AgentIdentitySnapshot.capture(member, manager) for member in (*parent.members, *team.members)}
        before = manager._records.snapshot()
        dirty = manager._new_dirty_state()
        dirty["configs"] = True
        dirty["inboxes"].add(team.team_id)
        snapshot = manager._capture_state_snapshot(dirty)
        await asyncio.wrap_future(manager._persistence.submit(path, snapshot))
        state = await manager._persistence.read(path, reconcile=False)
        await asyncio.to_thread(manager._validate_state_snapshot, state)
        self.assertEqual(manager._records.snapshot(), before)
        for member in (*parent.members, *team.members):
            self.assertEqual(AgentIdentitySnapshot.capture(member, manager), identities[member.agent_id])
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM team_members").fetchone(), (6,))
            self.assertEqual(database.execute("SELECT count(*) FROM membership_intervals").fetchone(), (6,))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(client.requests, [])

    async def test_failed_provisional_formation_does_not_publish_relationship_history(self):
        for independent_commit in (False, True):
            with self.subTest(independent_commit=independent_commit):
                manager, _, client = make_manager(self, volatile=True)
                manager.config.model_token_limits["fixture"] = 0
                invitees = [manager.register_agent(Agent(f"Founder-{index}", "Researcher", client)) for index in range(3)]
                request = manager.create_agent_team(manager.root_ai, parent=manager.root_ai, existing_members=invitees)
                for person in invitees:
                    await manager.respond_team_invitation(request.request_id, proposal_revision=1, actor=person, attitude="accepted")
                await self.settle_resource_blocked_mail(manager)
                before = manager._records.snapshot()
                graph = invocation_graph(manager.root_ai.agent_id)
                async def fail_commit(dirty, *, operation_id=None, authority_check=None):
                    self.assertTrue(dirty["_provisional"])
                    self.assertTrue(dirty["teams"])
                    self.assertEqual(operation_id, f"FORMATION-CREATE-{request.request_id}")
                    self.assertEqual(manager._records.snapshot(), before)
                    if independent_commit:
                        await manager._records.commit(graph, operation_id="independent-operation")
                    raise OSError("Injected provisional formation failure")
                with patch.object(manager, "_commit_dirty_state", fail_commit):
                    with self.assertRaisesRegex(OSError, "provisional formation"):
                        await manager.create_team_from_formation(request.request_id, proposal_revision=1, actor=manager.root_ai)
                self.assertEqual(manager.teams, {})
                expected = {row.identity: row for row in before}
                if independent_commit:
                    expected.update({row.identity: row for row in graph})
                self.assertEqual({row.identity: row for row in manager._records.snapshot()}, expected)
                self.assertEqual(manager.get_team_formation(request.request_id).status.value, "ready_for_confirmation")
                await manager._records.commit(graph, operation_id="independent-operation")
                self.assertEqual(client.requests, [])
