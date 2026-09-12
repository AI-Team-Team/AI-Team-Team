import shutil
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse


class CapturingNativeClient:
    def __init__(self):
        self.calls = []

    async def generate(
        self,
        prompt,
        system_instruction=None,
        require_json=False,
        **kwargs,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "system_instruction": system_instruction or "",
                "require_json": require_json,
            }
        )
        return LLMResponse(text="Final Answer: done")

    def supports_native_tool_calling(self):
        return True


class TestPromptIdentityConsistency(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-prompt-identity-")
        self.client = CapturingNativeClient()
        self.manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        self.manager.register_llm_client("capture", self.client)
        self.mission = "INDIVIDUAL_MISSION: Preserve evidence provenance."
        self.agent = Agent(
            "Specialist",
            "Researcher",
            self.client,
            system_instructions=self.mission,
        )
        self.manager.register_agent(self.agent)
        self.team = self.manager.create_agent_team(
            self.manager.root_ai,
            existing_members=[self.agent],
            member_configs={"HelperA": {}, "HelperB": {}},
            system_instructions="TEAM_ONE: Verify every conclusion.",
        )

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_agent_instructions_reach_native_and_auto_modes(self):
        for mode in ("native", "auto"):
            with self.subTest(mode=mode):
                self.manager.config.tool_calling_mode = mode
                self.client.calls.clear()
                await self.team.execute_reasoning_step_detailed(
                    self.agent,
                    "Review the evidence.",
                    self.team.system_instructions,
                    manager=self.manager,
                )
                system_instruction = self.client.calls[-1]["system_instruction"]
                self.assertIn(self.mission, system_instruction)
                self.assertIn(self.team.system_instructions, system_instruction)

    async def test_agent_instructions_reach_text_mode_without_tools(self):
        self.manager.config.tool_calling_mode = "text_react"
        self.client.calls.clear()
        with patch.object(self.manager, "get_available_tools", return_value={}):
            await self.team.execute_reasoning_step_detailed(
                self.agent,
                "Review without tools.",
                self.team.system_instructions,
                manager=self.manager,
            )
        system_instruction = self.client.calls[-1]["system_instruction"]
        self.assertIn(self.mission, system_instruction)
        self.assertIn(self.team.system_instructions, system_instruction)

    async def test_agent_instructions_reach_text_mode_with_tools(self):
        self.manager.config.tool_calling_mode = "text_react"
        self.client.calls.clear()
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Review with the available tools.",
            self.team.system_instructions,
            manager=self.manager,
        )
        system_instruction = self.client.calls[-1]["system_instruction"]
        self.assertIn(self.mission, system_instruction)
        self.assertIn(self.team.system_instructions, system_instruction)
        self.assertIn("### AVAILABLE TOOLS", system_instruction)

    async def test_shared_agent_keeps_mission_with_each_current_team(self):
        other_team = self.manager.create_agent_team(
            self.manager.root_ai,
            existing_members=[self.agent],
            member_configs={"OtherA": {}, "OtherB": {}},
            system_instructions="TEAM_TWO: Challenge every assumption.",
        )
        self.manager.config.tool_calling_mode = "native"

        captured = []
        for team in (self.team, other_team):
            self.client.calls.clear()
            await team.execute_reasoning_step_detailed(
                self.agent,
                "Continue the shared work.",
                team.system_instructions,
                manager=self.manager,
            )
            captured.append(self.client.calls[-1]["system_instruction"])

        self.assertIn(self.mission, captured[0])
        self.assertIn(self.mission, captured[1])
        self.assertIn("TEAM_ONE", captured[0])
        self.assertNotIn("TEAM_TWO", captured[0])
        self.assertIn("TEAM_TWO", captured[1])
        self.assertNotIn("TEAM_ONE", captured[1])
