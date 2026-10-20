"""Foreground effects never bypass reservations, provenance, or executor bindings."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

from ai_team_team import Agent, ResourceClaim, ToolBusinessError
from ai_team_team.core.activity.contracts import AgentTeamScope, ToolExecutionContract
from test.test_att.test_agent_activity._support import call, idle, personal_control_contract

from . import test_resources_and_privacy as fixtures
from ._support import BackgroundTestCase, contract


class ForegroundContractTests(BackgroundTestCase):
    async def test_mixed_effect_foreground_waits_for_the_same_background_resource(self):
        started, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        invoked = []
        claim = ResourceClaim(namespace="external", resource_id="shared-object", access="write")

        async def background() -> str:
            started.set()
            await release.wait()
            return "background completed"

        async def foreground() -> str:
            session = self.manager._activity.current.get()
            invoked.append((session, self.manager._active_tool_agent.get()))
            self.assertNotIn(handle.execution_id, self.manager._executions.resources.active)
            return "foreground completed"

        self.manager.register_tool("background", func=background, resource_resolver=lambda scope, arguments: (claim,),
            execution_contract=contract(effects=("artifact_write",), mutation_safety="managed_lease"))
        self.manager.register_tool("foreground", func=foreground, resource_resolver=lambda scope, arguments: (claim,),
            execution_contract=ToolExecutionContract(effects=("self_modification", "artifact_write"),
                background_allowed=False, required_scope="personal", mutation_safety="managed_lease"))
        handle = await self.start("background")
        await asyncio.wait_for(started.wait(), 5)
        hold = self.manager._executions.resources.hold

        @asynccontextmanager
        async def observed(execution_id, claims):
            waiting.set()
            async with hold(execution_id, claims):
                yield

        self.steps(call("foreground"), idle())
        with patch.object(self.manager._executions.resources, "hold", observed):
            admitted = await self.manager.activate_agent(self.root.agent_id)
            try:
                await asyncio.wait_for(waiting.wait(), 5)
                self.assertFalse(invoked)
            finally:
                release.set()
            await self.finish(handle)
            await self.wait(admitted)
        self.assertIs(invoked[0][0], self.manager._activity.admissions[admitted.admission_id])
        self.assertIs(invoked[0][1], self.root)

    async def test_mixed_effect_reservation_blocks_new_background_dispatch(self):
        started, release = asyncio.Event(), asyncio.Event()
        invoked = []
        claim = ResourceClaim(namespace="external", resource_id="shared-object", access="write")

        async def foreground() -> str:
            started.set()
            await release.wait()
            return "done"

        async def background() -> str:
            invoked.append(True)
            return "done"

        self.manager.register_tool("foreground", func=foreground, resource_resolver=lambda scope, arguments: (claim,),
            execution_contract=ToolExecutionContract(effects=("self_modification", "artifact_write"),
                background_allowed=False, required_scope="personal", mutation_safety="managed_lease"))
        self.manager.register_tool("background", func=background, resource_resolver=lambda scope, arguments: (claim,),
            execution_contract=contract(effects=("artifact_write",), mutation_safety="managed_lease"))
        self.steps(call("foreground"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(started.wait(), 5)
        handle = await self.start("background")
        try:
            self.assertFalse(invoked)
            self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "queued")
        finally:
            release.set()
        await self.wait(admitted)
        await self.finish(handle)
        self.assertEqual(invoked, [True])

    async def revoked_foreground_source(self, *, failure):
        _source, reader, library = fixtures.RetainedResultTests.teams(self)
        owner = reader.members[0]
        entered, release = asyncio.Event(), asyncio.Event()
        resolutions = []

        async def personal_read() -> str:
            self.assertEqual(self.manager._activity.current.get().agent_id, owner.agent_id)
            body = library.read_text("source.txt")
            entered.set()
            await release.wait()
            if failure:
                raise ToolBusinessError("Validation failed: " + body)
            return body

        def resources(scope, arguments):
            resolutions.append(scope)
            return (ResourceClaim(namespace="library", resource_id=library.lib_id, path="source.txt", access="read"),)

        self.manager.register_tool("personal_read", func=personal_read, resource_resolver=resources,
            execution_contract=ToolExecutionContract(effects=("self_modification", "read_only"),
                background_allowed=False, required_scope="agent_team"))
        self.steps(call("personal_read"), idle())
        admitted = await self.manager.activate_agent(owner.agent_id, scope=AgentTeamScope(team_id=reader.team_id))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.manager._resources.mutation():
                self.manager.library_permissions[library.lib_id]["/"].pop(reader.team_id)
        finally:
            release.set()
        await self.wait(admitted)
        execution = next(row for row in self.records("executions") if row.values["tool_name"] == "personal_read")
        execution_id = execution.values["execution_id"]
        self.assertTrue(resolutions)
        self.assertEqual(execution.values["status"], "failed")
        self.assertEqual(execution.values["source_references"][0]["lib_id"], library.lib_id)
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", str(self.records("execution_payloads")))
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", str(owner.message_history))
        self.assertEqual(self.manager._executions.jobs[execution_id].result.status.value, "denied")
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT",
            (await self.manager.read_background_task_result(execution_id, actor=owner)).content)
        self.manager.config.executions.retain_results_after_source_revocation = False
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(execution_id, actor=owner)

    async def test_mixed_effect_success_revalidates_sources_before_acceptance(self):
        await self.revoked_foreground_source(failure=False)

    async def test_mixed_effect_failure_body_revalidates_sources_before_acceptance(self):
        await self.revoked_foreground_source(failure=True)

    async def test_self_modification_uses_its_registered_provider_not_the_placeholder(self):
        called = []
        sessions = []
        manager = self.manager

        class Provider:
            async def execute(self, call):
                called.append(("provider", call.owner_agent_id, call.arguments, dict(call.keywords)))
                sessions.append(manager._activity.current.get())
                return "provider result"

        def placeholder(value: str) -> str:
            called.append(("placeholder", value))
            return "must not execute"

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("personal_operation", func=placeholder, executor="provider",
            execution_contract=personal_control_contract())
        identity = (self.root.agent_id, self.root.llm_client, self.root.private_doc_library_id)
        self.steps(call("personal_operation", {"value": "validated"}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertEqual(called, [("provider", self.root.agent_id, ("validated",), {})])
        self.assertIs(sessions[0], self.manager._activity.admissions[admitted.admission_id])
        self.assertEqual(identity, (self.root.agent_id, self.root.llm_client, self.root.private_doc_library_id))
        row = next(row for row in self.records("executions") if row.values["tool_name"] == "personal_operation")
        self.assertEqual(row.values["contract_snapshot"]["executor"], "provider")
        self.assertEqual(row.values["status"], "completed")
        self.assertIn("provider result", self.manager._executions.jobs[row.values["execution_id"]].result.content)

    async def test_self_only_control_cannot_implicitly_access_managed_files(self):
        library = self.manager.libraries[self.root.private_doc_library_id]
        library.write_file("private.txt", "UNCLAIMED_PRIVATE_CONTENT")

        async def personal_read() -> str:
            return library.read_text("private.txt")

        self.manager.register_tool("personal_read", func=personal_read, execution_contract=personal_control_contract())
        self.steps(call("personal_read"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        row = next(row for row in self.records("executions") if row.values["tool_name"] == "personal_read")
        self.assertEqual(self.manager._executions.jobs[row.values["execution_id"]].result.status.value, "denied")
        self.assertNotIn("UNCLAIMED_PRIVATE_CONTENT", str(self.records("execution_payloads")))

    async def test_mixed_effect_nested_model_wait_is_rejected_before_mail_admission(self):
        other = Agent("Other", "Researcher", self.client)
        self.manager.register_agent(other)

        async def personal_coordinator() -> str:
            return str(await self.manager.execute_agent_interaction(other, "Do not accept a resource deadlock"))

        self.manager.register_tool("personal_coordinator", func=personal_coordinator,
            resource_resolver=lambda scope, arguments: (ResourceClaim(namespace="external", resource_id="shared"),),
            execution_contract=ToolExecutionContract(effects=("self_modification", "read_only"),
                background_allowed=False, required_scope="personal"))
        self.steps(call("personal_coordinator"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertFalse(other.agent_inbox)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        job = next(job for job in self.manager._executions.jobs.values() if job.tool.name == "personal_coordinator")
        self.assertEqual(job.result.status.value, "denied")
