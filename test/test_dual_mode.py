import os
import sys
import unittest
import asyncio
from typing import Dict, Any, List, Optional, TypedDict
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, Tool, ATTConfig, LLMResponse, ToolCall, ToolResult

# Pydantic support
try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

class TestDualModeToolCalling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

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

    def test_pythonic_tool_instantiation(self):
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
        manager = ATTManager(root_ai=mock_agent)
        manager.register_tool(my_test_tool)
        self.assertIn("my_test_tool", manager.global_tools)
        self.assertEqual(manager.global_tools["my_test_tool"].description, "Retrieve the value of x.")

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

    @unittest.skipUnless(HAS_PYDANTIC, "Pydantic not installed")
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
        """Verify that native mode concurrently executes multiple tool calls and returns final answer."""
        config = ATTConfig(tool_calling_mode="native", max_tool_rounds=2)
        
        # We will mock the LLM Client generate method
        mock_client = MagicMock()
        
        # Round 1 returns parallel tool calls, Round 2 returns text response
        responses = [
            LLMResponse(tool_calls=[
                ToolCall(call_id="call_1", name="tool_a", arguments={"val": 10}),
                ToolCall(call_id="call_2", name="tool_b", arguments={"val": 20})
            ]),
            LLMResponse(text="Final result of parallel execution is success")
        ]
        
        async def mock_generate(*args, **kwargs):
            return responses.pop(0)
            
        mock_client.generate = mock_generate
        mock_client.supports_native_tool_calling = lambda: True
        
        root_ai = Agent(name="Root", role="Architect", llm_client=mock_client)
        manager = ATTManager(root_ai=root_ai, config=config)
        
        # Register tools
        tool_a_runs = 0
        async def tool_a(val: int):
            nonlocal tool_a_runs
            tool_a_runs += 1
            await asyncio.sleep(0.01)
            return f"A: {val}"
            
        tool_b_runs = 0
        async def tool_b(val: int):
            nonlocal tool_b_runs
            tool_b_runs += 1
            await asyncio.sleep(0.01)
            return f"B: {val}"
            
        manager.register_tool("tool_a", "Run tool A", tool_a)
        manager.register_tool("tool_b", "Run tool B", tool_b)
        
        team = manager.create_agent_team(creator=root_ai, member_count=3)
        # Force members client to use mock_client
        for m in team.members:
            m.llm_client = mock_client
            
        ans = await team.execute_reasoning_step(team.members[0], "Start task", "System instructions")
        
        self.assertEqual(ans, "Final result of parallel execution is success")
        self.assertEqual(tool_a_runs, 1)
        self.assertEqual(tool_b_runs, 1)
        
        # Verify messages history format
        messages = team.members[0].messages
        # We expect user prompt, assistant tool call response, tool result answers, and assistant final answer
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertIsNotNone(messages[1].get("tool_calls"))
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[3]["role"], "tool")
        self.assertEqual(messages[4]["role"], "assistant")
        self.assertEqual(messages[4]["content"], "Final result of parallel execution is success")

    async def test_auto_mode_routing_fallback(self):
        """Verify auto-mode selects the correct reasoning strategy based on client capabilities."""
        # 1. Native capable client
        mock_native_client = MagicMock()
        mock_native_client.generate = AsyncMock(return_value=LLMResponse(text="Native Answer"))
        mock_native_client.supports_native_tool_calling = lambda: True
        
        agent_native = Agent(name="NativeAgent", role="Specialist", llm_client=mock_native_client)
        
        # 2. Text React fallback client
        mock_text_client = MagicMock()
        mock_text_client.generate = AsyncMock(return_value=LLMResponse(text="Final Answer: Text React Answer"))
        mock_text_client.supports_native_tool_calling = lambda: False
        
        agent_text = Agent(name="TextAgent", role="Specialist", llm_client=mock_text_client)
        
        config = ATTConfig(tool_calling_mode="auto")
        root_ai = Agent(name="Root", role="Architect", llm_client=mock_native_client)
        manager = ATTManager(root_ai=root_ai, config=config)
        team = manager.create_agent_team(creator=root_ai, member_count=3)
        
        ans_native = await team.execute_reasoning_step(agent_native, "Start", "System instructions", manager=manager)
        self.assertEqual(ans_native, "Native Answer")
        
        ans_text = await team.execute_reasoning_step(agent_text, "Start", "System instructions", manager=manager)
        self.assertEqual(ans_text, "Text React Answer")
