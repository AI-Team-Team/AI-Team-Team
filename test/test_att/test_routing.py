import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, ATTConfig

class TestATTRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)

    def test_heterogeneous_registry_mode1(self):
        """Verify Mode 1 (Dependency Injection) client registration and routing."""
        mock_custom_client = MagicMock()
        mock_custom_client.generate = AsyncMock(return_value="Custom Response")

        # Register custom client directly to dictionary
        self.manager.llm_clients["my-custom"] = mock_custom_client
        self.assertIn("my-custom", self.manager.llm_clients)

        # Spawn team and specify roles_and_models
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"],
            roles_and_models={"Specialist_A": "my-custom"}
        )

        # Check client assignment
        specialist_a = [m for m in team.members if m.name == "Specialist_A"][0]
        specialist_b = [m for m in team.members if m.name == "Specialist_B"][0]

        self.assertEqual(specialist_a.llm_client, mock_custom_client)
        self.assertEqual(specialist_b.llm_client, self.root_ai.llm_client)

    async def test_global_generator_handler_routing(self):
        """Verify model config registration, callback handler routing, and metadata in identity prompts."""
        # 1. Register a model configuration
        self.manager.register_model("gemini", {
            "model_type": "llm",
            "model_name": "gemini-3.5-flash",
            "ai_note": "gemini-3.5-flash - A very impressive large model"
        })
        self.assertIn("gemini", self.manager.model_configs)

        # 2. Register global generator callback
        generated_requests = []
        async def my_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            generated_requests.append({
                "model": model_name,
                "prompt": prompt,
                "system": system_instruction,
                "json": require_json
            })
            if require_json:
                return '{"is_healthy": true, "reason": "Approved"}'
            return "Final Answer: Handler Output"

        self.manager.register_generator_handler(my_handler)

        # 3. Spawn team and assign role to the model
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"],
            roles_and_models={"Specialist_A": "gemini"}
        )

        specialist_a = [m for m in team.members if m.name == "Specialist_A"][0]
        
        # 4. Trigger debate step
        res = await team.execute_react_step(specialist_a, "Test Task", "System instructions", max_steps=1, manager=self.manager)
        self.assertEqual(res, "Handler Output")
        self.assertEqual(len(generated_requests), 1)
        self.assertEqual(generated_requests[0]["model"], "gemini")
        # Ensure model's ai_note is present in system instructions passed to prompt builder
        self.assertIn("gemini-3.5-flash - A very impressive large model", generated_requests[0]["system"])

        # 5. Verify critic/supervisor routing fallback
        is_healthy, reason = await self.manager.supervisor.audit_team_dialog(team, "Dummy dialogue")
        self.assertTrue(is_healthy)
        self.assertEqual(reason, "Approved")
        self.assertEqual(len(generated_requests), 8) # Updated from 2 to 8 due to 3-AI committee debate (6 turns + 1 consensus)
        self.assertEqual(generated_requests[7]["model"], "default")
        self.assertTrue(generated_requests[7]["json"])

    async def test_dispatch_subagent_routing(self):
        """Verify that dispatch_subagent correctly propagates roles_and_models to dynamic child teams using configuration routing."""
        # Setup tools context
        self.manager.register_tools_context({"att_manager": self.manager})

        # Register config and generator callback
        self.manager.register_model("my-custom-model", {
            "model_type": "llm",
            "model_name": "custom-real-model",
            "ai_note": "custom model note"
        })
        
        called_models = []
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            called_models.append(model_name)
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )

        dispatch_tool = team.tools["dispatch_subagent"]

        # Intercept execute_team_discussion to check the spawned team
        original_execute = self.manager.execute_team_discussion
        captured_child_team = None

        async def mock_execute_team_discussion(child_team, prompt, rounds=2):
            nonlocal captured_child_team
            captured_child_team = child_team
            return "Mocked debate result"

        self.manager.execute_team_discussion = mock_execute_team_discussion

        try:
            await dispatch_tool(
                task="Do task",
                team_purpose="Sub task",
                member_configs={
                    "Planner": {"model": "my-custom-model"},
                    "Researcher": {"model": "my-custom-model"},
                    "Writer": {"model": "my-custom-model"}
                },
                system_instructions="Adhere to rules"
            )
        finally:
            self.manager.execute_team_discussion = original_execute

        self.assertIsNotNone(captured_child_team)
        self.assertEqual(captured_child_team.depth, 2)
        # Sibling names in dynamic dispatch are "Dynamic_{role_name}"
        # Let's verify client routing on the spawned child team members
        planner_member = [m for m in captured_child_team.members if m.role == "Planner"][0]
        self.assertEqual(planner_member.llm_client.model_name, "my-custom-model")
        self.assertEqual(planner_member.llm_client.handler, mock_handler)

    async def test_dispatch_subagent_dynamic_member_count_validation(self):
        """Verify dynamic subagent member count resolution and validation from member_configs."""
        self.manager.register_tools_context({"att_manager": self.manager})

        called_models = []
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            called_models.append(model_name)
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )

        dispatch_tool = team.tools["dispatch_subagent"]

        # 1. Spawn dynamic subagent with 3 dynamic roles -> success
        res = await dispatch_tool(
            task="Do task",
            team_purpose="Sub task",
            member_configs={
                "Code_Architect": {"model": "default"},
                "Security_Auditor": {"model": "default"},
                "Quality_Assurance": {"model": "default"}
            },
            system_instructions="Adhere to rules"
        )
        self.assertNotIn("Error", res)

        # 2. Spawn dynamic subagent with 2 dynamic roles -> failure (min_subagent_team_size is 3)
        res_fail = await dispatch_tool(
            task="Do task",
            team_purpose="Sub task",
            member_configs={
                "Architect": {"model": "default"},
                "Reviewer": {"model": "default"}
            },
            system_instructions="Adhere to rules"
        )
        self.assertIn("Error", res_fail)
        self.assertIn("MUST have at least 3 members", res_fail)

    async def test_member_configs_spawning_and_prompting(self):
        """Verify dynamic role prompts and ai_note prompt injection."""
        self.manager.register_tools_context({"att_manager": self.manager})
        self.manager.register_model("my-custom-model", {
            "model_type": "llm",
            "model_name": "custom-real-model",
            "ai_note": "A very impressive large model"
        })

        system_instruction_captured = None
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            nonlocal system_instruction_captured
            system_instruction_captured = system_instruction
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

        # Create a child team using member_configs
        member_configs = {
            "Lead_Planner": {
                "model": "my-custom-model",
                "role_description": "Responsible for structural orchestration and task scheduling.",
                "system_instructions": "Prioritize clarity, decompose objectives, and verify sub-tasks."
            },
            "Senior_Researcher": {
                "model": "default",
                "role_description": "Responsible for factual lookup.",
                "system_instructions": "Ensure sources are reliable."
            },
            "Technical_Writer": {
                "model": "default",
                "role_description": "Responsible for drafting cohesive documents.",
                "system_instructions": "Maintain high readability."
            }
        }

        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs=member_configs
        )

        self.assertEqual(len(team.members), 3)
        planner = [m for m in team.members if m.role == "Lead_Planner"][0]
        self.assertEqual(planner.role_description, "Responsible for structural orchestration and task scheduling.")
        self.assertEqual(planner.system_instructions, "Prioritize clarity, decompose objectives, and verify sub-tasks.")

        # Run execute_react_step on Lead_Planner to capture system instructions
        await team.execute_react_step(planner, "Start task", "Base system instruction", max_steps=1, manager=self.manager)

        self.assertIsNotNone(system_instruction_captured)
        self.assertIn("Prioritize clarity, decompose objectives, and verify sub-tasks.", system_instruction_captured)
        self.assertIn("Responsible for structural orchestration and task scheduling.", system_instruction_captured)
        self.assertIn("my-custom-model: A very impressive large model", system_instruction_captured)

if __name__ == "__main__":
    unittest.main()
