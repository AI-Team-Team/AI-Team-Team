"""The red suite targets the real Manager, never a fake activity implementation."""

import asyncio
import json
import tempfile
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse, ToolCall

from ._fixtures import LogicalClock, ScriptedModelClient
from ._fixtures.model import CapturedRequest


def idle_response(call_id="idle-choice"):
    return LLMResponse(
        tool_calls=[ToolCall(call_id, "set_activity_intent", {"intent": {"kind": "idle"}})]
    )


def model_input(request: CapturedRequest, *, notification_only: bool = False) -> str:
    prompt = request.prompt
    if notification_only:
        prompt = [item for item in prompt if item.get("role") in {"user", "system"}]
    return json.dumps({"system_instruction": request.system_instruction, "prompt": prompt})


class RuntimeSpecFixture:
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-phase0-red-")
        self.addCleanup(self.workspace.cleanup)
        self.clock = LogicalClock()
        self.addCleanup(self.clock.close)
        self.client = ScriptedModelClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.workspace.name, tool_calling_mode="native"),
            db_path=str(Path(self.workspace.name) / "state.sqlite"),
        )
        self.addAsyncCleanup(self.manager.close)
        self.manager.register_llm_client("fixture", self.client)
        self.person = Agent("Mira", "Researcher", self.client)
        self.manager.register_agent(self.person)
        self.first = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[self.person],
            member_configs={f"First{index}": {"model": "fixture"} for index in range(2)},
        )
        self.second = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[self.person],
            member_configs={f"Second{index}": {"model": "fixture"} for index in range(2)},
        )

    async def asyncTearDown(self):
        await self.manager.close()
        self.assertEqual(
            self.client.unexpected_requests,
            0,
            "The runtime attempted extra model requests, even if it swallowed their errors.",
        )

    def require_method(self, name):
        method = getattr(self.manager, name, None)
        self.assertTrue(
            callable(method), f"Missing autonomous runtime contract: ATTManager.{name}."
        )
        return method

    async def wait_idle(self, admission_id):
        wait = self.require_method("wait_for_activity_checkpoint")
        return await asyncio.wait_for(wait(admission_id, intent="idle"), timeout=5)
