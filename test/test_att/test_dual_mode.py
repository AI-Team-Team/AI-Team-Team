import os
import sys
import unittest
import asyncio
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, Tool, ATTConfig, LLMResponse, ToolCall
from test.personal_activity import interact_and_idle

class TestDualModeToolCalling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)
        self.addCleanup(os.chdir, self._test_old_cwd)

    async def test_schema_auto_generation_signature(self):
        """Verify tool schema auto-generation using python signature inspection."""
        def dummy_tool(city: str, limit: int = 3) -> str:
            return f"Weather in {city} with limit {limit}"

        tool = Tool(name="weather", description="Query weather", func=dummy_tool)
        schema = tool.json_schema
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["city"]["type"], "string")
        self.assertEqual(schema["properties"]["limit"]["type"], "integer")
        self.assertEqual(schema["properties"]["limit"]["default"], 3)
        self.assertIn("city", schema["required"])
        self.assertNotIn("limit", schema["required"])

    async def test_pythonic_tool_instantiation(self):
        """Verify Tool can be instantiated using Pythonic constructor shortcuts."""
        def my_test_tool(x: int) -> int:
            """Retrieve the value of x.
            Detailed description.
            """
            return x

        # 1. Positional function passing
        t1 = Tool(my_test_tool)
        self.assertEqual(t1.name, "my_test_tool")
        self.assertEqual(t1.description, "Retrieve the value of x.")
        self.assertEqual(t1.func, my_test_tool)
        self.assertEqual(t1.json_schema["properties"]["x"]["type"], "integer")

        # 2. Keyword function passing
        t2 = Tool(func=my_test_tool)
        self.assertEqual(t2.name, "my_test_tool")
        self.assertEqual(t2.description, "Retrieve the value of x.")
        self.assertEqual(t2.func, my_test_tool)

        # 3. Keyword function passing with custom schema
        custom_schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        t3 = Tool(func=my_test_tool, schema=custom_schema)
        self.assertEqual(t3.json_schema, custom_schema)

        # 4. manager.register_tool shortcut
        mock_client = MagicMock()
        mock_agent = Agent(name="TestAgent", role="Tester", llm_client=mock_client)
        manager = ATTManager(root_ai=mock_agent, persistence_mode="volatile")
        manager.register_tool(my_test_tool)
        self.assertIn("my_test_tool", manager.global_tools)
        self.assertEqual(manager.global_tools["my_test_tool"].description, "Retrieve the value of x.")
        await manager.close()

    async def test_schema_generation_handwritten(self):
        """Verify tool schema using custom dict override."""
        def dummy_tool(city):
            return city
            
        custom_schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
        tool = Tool(name="weather", description="Query", func=dummy_tool, schema=custom_schema)
        self.assertEqual(tool.json_schema, custom_schema)

    async def test_schema_generation_typed_dict(self):
        """Verify tool schema using TypedDict definition."""
        class WeatherArgs(TypedDict):
            city: str
            days: int

        def dummy_tool(args: WeatherArgs):
            return args
            
        tool = Tool(name="weather", description="Query", func=dummy_tool, schema=WeatherArgs)
        schema = tool.json_schema
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["city"]["type"], "string")
        self.assertEqual(schema["properties"]["days"]["type"], "integer")
        self.assertIn("city", schema["required"])
        self.assertIn("days", schema["required"])

    def test_schema_generation_pydantic(self):
        """Verify tool schema using Pydantic model definition."""
        class WeatherModel(BaseModel):
            city: str = Field(description="Target city")
            days: int = 3

        def dummy_tool(args):
            return args

        tool = Tool(name="weather", description="Query", func=dummy_tool, schema=WeatherModel)
        schema = tool.json_schema
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["city"]["type"], "string")
        self.assertEqual(schema["properties"]["days"]["type"], "integer")
        self.assertIn("city", schema["required"])

    async def test_native_mode_parallel_execution(self):
        """Independent native tool calls share a batch, not a team round."""
        responses = [
            LLMResponse(tool_calls=[
                ToolCall(call_id="call_1", name="tool_a", arguments={"val": 10}),
                ToolCall(call_id="call_2", name="tool_b", arguments={"val": 20}),
            ]),
            LLMResponse(text="Final result of parallel execution is success"),
            LLMResponse(tool_calls=[ToolCall("idle", "set_activity_intent", {"intent": {"kind": "idle"}})]),
        ]
        client = MagicMock()
        client.generate = AsyncMock(side_effect=responses)
        client.supports_native_tool_calling = lambda: True
        manager = ATTManager(Agent("Root", "Architect", client),
            ATTConfig(tool_calling_mode="native"), persistence_mode="volatile")
        self.addAsyncCleanup(manager.close)
        started = set()
        both_started = asyncio.Event()

        async def perform(name, val):
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 5)
            return f"{name}: {val}"

        async def tool_a(val: int):
            return await perform("A", val)

        async def tool_b(val: int):
            return await perform("B", val)

        manager.register_tool("tool_a", "Run tool A", tool_a)
        manager.register_tool("tool_b", "Run tool B", tool_b)
        team = manager.create_agent_team(creator=manager.root_ai)
        person = team.members[0]
        result = await interact_and_idle(manager, person, "Start task", team=team)
        self.assertEqual(result.answer, "Final result of parallel execution is success")
        self.assertEqual(started, {"A", "B"})
        messages = person.messages
        call_index = next(index for index, item in enumerate(messages) if item.get("tool_calls"))
        self.assertEqual([item["role"] for item in messages[call_index:call_index + 3]],
            ["assistant", "tool", "tool"])
        self.assertEqual({item["tool_call_id"] for item in messages[call_index + 1:call_index + 3]},
            {"call_1", "call_2"})

    async def test_auto_mode_routing_fallback(self):
        """Actual personal activity uses the selected provider-neutral mode."""
        native = MagicMock()
        native.generate = AsyncMock(side_effect=[
            LLMResponse(text="Native Answer"),
            LLMResponse(tool_calls=[ToolCall("idle-native", "set_activity_intent", {"intent": {"kind": "idle"}})]),
        ])
        native.supports_native_tool_calling = lambda: True
        text = MagicMock()
        text.generate = AsyncMock(side_effect=[
            "Final Answer: Text ReAct Answer",
            "Action: set_activity_intent(intent={'kind': 'idle'})",
        ])
        text.supports_native_tool_calling = lambda: False
        manager = ATTManager(Agent("Root", "Architect", native),
            ATTConfig(tool_calling_mode="auto"), persistence_mode="volatile")
        self.addAsyncCleanup(manager.close)
        native_person = manager.register_agent(Agent("NativeAgent", "Specialist", native))
        text_person = manager.register_agent(Agent("TextAgent", "Specialist", text))
        result = await interact_and_idle(manager, native_person, "Start")
        self.assertEqual(result.answer, "Native Answer")
        result = await interact_and_idle(manager, text_person, "Start")
        self.assertEqual(result.answer, "Text ReAct Answer")
        self.assertTrue(all(isinstance(item, Tool) for item in native.generate.call_args_list[0].kwargs["tools"]))
