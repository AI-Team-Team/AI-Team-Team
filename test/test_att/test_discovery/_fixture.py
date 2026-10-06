"""Temporary-workspace fixtures with no external model calls."""

import copy
import json
import tempfile

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse


class CaptureClient:
    def __init__(self):
        self.calls = []
        self.response = None

    def supports_native_tool_calling(self):
        return False

    async def generate(self, prompt=None, system_instruction=None, require_json=False, **kwargs):
        self.calls.append(
            {
                "prompt": copy.deepcopy(prompt),
                "system_instruction": system_instruction,
                "tool_names": [tool.name for tool in kwargs.get("tools") or []],
            }
        )
        if self.response is not None:
            return self.response(prompt, require_json=require_json, **kwargs)
        if require_json:
            return json.dumps({"is_healthy": True, "reason": "Synthetic audit."})
        return LLMResponse(text="Final Answer: Completed the ordinary interaction.")


class DiscoveryFixture:
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-discovery-test-")
        self.addCleanup(self.workspace.cleanup)
        self.client = CaptureClient()
        self.root = Agent(
            "ZRoot", "Architect", self.client, system_instructions="CONTINUING_PERSONAL_MISSION"
        )
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.workspace.name, enable_memory_compression=False),
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)

    def person(self, name, role="Researcher", description=""):
        agent = Agent(name, role, self.client, role_description=description)
        self.manager.register_agent(agent)
        return agent
