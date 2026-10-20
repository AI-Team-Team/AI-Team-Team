"""A nested person's invocation never inherits another operation's resource claims."""

from ai_team_team import Agent, ResourceClaim
from ai_team_team.core.activity.contracts import ToolExecutionContract
from test.test_att.test_agent_activity._support import call, idle, personal_control_contract
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep, ScriptedModelClient

from ._support import BackgroundTestCase


class InvocationResourceBoundaryTests(BackgroundTestCase):
    async def test_source_free_control_preserves_nested_institutional_tool_execution(self):
        client = ScriptedModelClient(ModelStep(call("write_private_file", {
            "path": "notes.txt", "content": "NESTED_PERSONAL_ARTIFACT"})), ModelStep("Final Answer: Written."))
        self.manager.register_llm_client("nested", client)
        other = Agent("Nested", "Researcher", client)
        self.manager.register_agent(other)
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[other],
            member_configs={f"Helper{i}": {"model": "fixture"} for i in range(2)})
        observed = []

        async def coordinate() -> str:
            session = self.manager._activity.current.get()
            job = self.manager._executions.resource_job.get()
            answer = await team.execute_reasoning_step(other, "Write your own artifact.", "Use the requested tool.", manager=self.manager)
            observed.append((self.manager._activity.current.get() is session,
                self.manager._executions.resource_job.get() is job))
            return answer

        self.manager.register_tool("coordinate", func=coordinate, execution_contract=personal_control_contract(),
            resource_resolver=lambda scope, arguments: ())
        self.steps(call("coordinate"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        library = self.manager.libraries[other.private_doc_library_id]
        self.assertEqual(library.read_text("notes.txt"), "NESTED_PERSONAL_ARTIFACT")
        self.assertEqual(observed, [(True, True)])
        self.assertEqual(len(client.requests), 2)
        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_shared_reservation_cannot_enter_a_direct_model_invocation(self):
        other = Agent("Nested", "Researcher", self.client)
        self.manager.register_agent(other)
        entered = []

        async def coordinate() -> str:
            async with self.manager.agent_invocation(other):
                entered.append(True)
            return "must not enter"

        self.manager.register_tool("coordinate", func=coordinate,
            resource_resolver=lambda scope, arguments: (ResourceClaim(namespace="external", resource_id="shared"),),
            execution_contract=ToolExecutionContract(effects=("self_modification", "read_only"),
                background_allowed=False, required_scope="personal"))
        self.steps(call("coordinate"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertFalse(entered)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertEqual(self.manager._active_invocations, 0)
        job = next(job for job in self.manager._executions.jobs.values() if job.tool.name == "coordinate")
        self.assertEqual(job.result.status.value, "denied")
