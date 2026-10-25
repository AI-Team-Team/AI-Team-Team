"""Returned facts settle before death without admitting new effects or losing ACL checks."""

import asyncio
import threading
from unittest.mock import Mock, patch

from ai_team_team import Agent
from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.core.execution import ResourceClaim
from test.test_att.test_agent_activity._support import ActivityTestCase

from ._support import contract


class LifecycleOutcomeTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager._activity.schedule_notice = Mock()
        self.person = self.manager.register_agent(Agent("Owner", "Researcher", self.client))

    def team_for_owner(self):
        return self.manager.bootstrap_agent_team(self.root, existing_members=[self.person],
            member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}})

    def preparation_barrier(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._executions.prepare_result

        async def prepare(tool, result):
            prepared = await original(tool, result)
            if tool.name == "operation":
                entered.set()
                await release.wait()
            return prepared

        return entered, release, prepare

    async def finish_during_death(self, handle, release, *, expected="completed", content="RETURNED_FACT", cancel_observer=False):
        owner = self.person.agent_id
        dying = asyncio.create_task(self.manager.mark_agent_dead(owner, confirm=True))
        try:
            async with asyncio.timeout(10):
                while owner not in self.manager._agent_registry.lifecycle_pending:
                    await asyncio.sleep(0)
            if cancel_observer:
                dying.cancel()
            # An independent exact export crosses the domain queue while the
            # returned outcome is still preparing. No external wait is needed.
            await self.manager.save_state(full=False)
            self.assertEqual(self.person.lifecycle_state, "active")
            self.assertFalse(dying.done())
            release.set()
            if cancel_observer:
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(dying, 10)
            else:
                await asyncio.wait_for(dying, 10)
            row = self.manager._records.index[("executions", (handle.execution_id,))]
            payload = self.manager._records.index[("execution_payloads", (f"RESULT-{handle.execution_id}",))]
            self.assertEqual(row.values["status"], expected)
            self.assertIn(content, payload.values["content"]["content"])
            self.assertEqual(self.person.lifecycle_state, "dead")
            state = await self.manager._persistence.read(self.manager.db_path, reconcile=False)
            self.assertIn(row, state["records"])
            self.assertIn(payload, state["records"])
            self.assertFalse(self.manager._executions.pending_owner_outcomes(owner))
        finally:
            release.set()
            await asyncio.gather(dying, return_exceptions=True)

    async def test_returned_personal_result_survives_death_and_observer_cancellation(self):
        async def operation():
            return "RETURNED_FACT"
        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        entered, release, prepare = self.preparation_barrier()
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                handle = await self.manager.start_background_task("operation", {}, actor=self.person)
                await asyncio.wait_for(entered.wait(), 10)
                await self.finish_during_death(handle, release, cancel_observer=True)
            finally:
                release.set()

    async def test_team_result_settles_before_death_closes_its_membership(self):
        team = self.team_for_owner()
        async def operation():
            return "RETURNED_FACT"
        self.manager.register_tool("operation", func=operation,
            execution_contract=contract(required_scope="agent_team"))
        entered, release, prepare = self.preparation_barrier()
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                handle = await self.manager.start_background_task("operation", {}, actor=self.person,
                    scope=AgentTeamScope(team_id=team.team_id))
                await asyncio.wait_for(entered.wait(), 10)
                await self.finish_during_death(handle, release)
                self.assertNotIn(self.person, team.members)
            finally:
                release.set()

    async def test_an_outcome_arriving_while_death_waits_for_team_locks_still_wins(self):
        team = self.team_for_owner()
        started, returned = asyncio.Event(), asyncio.Event()
        async def operation():
            started.set()
            await returned.wait()
            return "RETURNED_FACT"
        self.manager.register_tool("operation", func=operation,
            execution_contract=contract(required_scope="agent_team"))
        handle = await self.manager.start_background_task("operation", {}, actor=self.person,
            scope=AgentTeamScope(team_id=team.team_id))
        await asyncio.wait_for(started.wait(), 10)
        entered, release, prepare = self.preparation_barrier()
        await team.state_lock.acquire()
        held, dying = True, None
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                dying = asyncio.create_task(self.manager.mark_agent_dead(self.person.agent_id, confirm=True))
                async with asyncio.timeout(10):
                    while self.person.agent_id not in self.manager._agent_registry.lifecycle_pending:
                        await asyncio.sleep(0)
                returned.set()
                await asyncio.wait_for(entered.wait(), 10)
                team.state_lock.release()
                held = False
                await self.manager.save_state(full=False)
                self.assertEqual(self.person.lifecycle_state, "active")
                release.set()
                await asyncio.wait_for(dying, 10)
                self.assertEqual(self.manager._records.index[("executions", (handle.execution_id,))].values["status"], "completed")
            finally:
                returned.set()
                release.set()
                if held:
                    team.state_lock.release()
                if dying is not None:
                    await asyncio.gather(dying, return_exceptions=True)

    async def test_source_revocation_still_denies_a_returned_result_during_death(self):
        consumer = self.team_for_owner()
        source = self.manager.create_agent_team(self.root)
        source.doc_library.write_file("data.txt", "SOURCE_BODY")
        await self.manager._library_service.change_permission(source, source.doc_library.lib_id,
            "/", consumer.team_id, "READ")
        async def operation():
            return "SENSITIVE_RETURNED_BODY"
        self.manager.register_tool("operation", func=operation,
            execution_contract=contract(required_scope="agent_team"),
            resource_resolver=lambda scope, arguments: (
                ResourceClaim(namespace="library", resource_id=source.doc_library.lib_id, path="data.txt", access="read"),))
        entered, release, prepare = self.preparation_barrier()
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                handle = await self.manager.start_background_task("operation", {}, actor=self.person,
                    scope=AgentTeamScope(team_id=consumer.team_id))
                await asyncio.wait_for(entered.wait(), 10)
                await self.manager._library_service.change_permission(source, source.doc_library.lib_id,
                    "/", consumer.team_id, None)
                await self.finish_during_death(handle, release, expected="failed", content="Source permission changed")
                payload = self.manager._records.index[("execution_payloads", (f"RESULT-{handle.execution_id}",))]
                self.assertNotIn("SENSITIVE_RETURNED_BODY", str(payload.values))
            finally:
                release.set()

    async def test_already_returned_synchronous_result_is_drained_without_replay(self):
        started, return_now = threading.Event(), threading.Event()
        calls = []
        def operation():
            calls.append(True)
            started.set()
            if not return_now.wait(10):
                raise TimeoutError("The synchronous result was not released.")
            return "RETURNED_FACT"
        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.manager.start_background_task("operation", {}, actor=self.person)
        job = self.manager._executions.jobs[handle.execution_id]
        entered, release, prepare = self.preparation_barrier()
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 10))
                await self.manager.cancel_background_task(handle.execution_id, actor=self.person)
                await asyncio.wait_for(job.finished.wait(), 10)
                return_now.set()
                await asyncio.wait_for(entered.wait(), 10)
                await self.finish_during_death(handle, release)
                self.assertEqual(calls, [True])
            finally:
                return_now.set()
                release.set()
                await asyncio.gather(*tuple(job.pending_threads), return_exceptions=True)

    async def test_another_owners_returned_result_does_not_delay_death(self):
        async def operation():
            return "Another person's result"
        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        entered, release, prepare = self.preparation_barrier()
        with patch.object(self.manager._executions, "prepare_result", prepare):
            try:
                handle = await self.manager.start_background_task("operation", {}, actor=self.root)
                await asyncio.wait_for(entered.wait(), 10)
                await asyncio.wait_for(self.manager.mark_agent_dead(self.person.agent_id, confirm=True), 10)
                self.assertEqual(self.person.lifecycle_state, "dead")
                self.assertFalse(self.manager._executions.jobs[handle.execution_id].outcome_task.done())
            finally:
                release.set()
