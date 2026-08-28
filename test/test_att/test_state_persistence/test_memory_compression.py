from test.test_att.test_state_persistence._support import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTeam,
    AgreementDirection,
    ApprovalPrincipal,
    AsyncMock,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationRequest,
    CommunicationRequestStatus,
    DocumentLibrary,
    MagicMock,
    StatePersistenceTestCase,
    json,
    os,
    route_fingerprint,
    sqlite3,
    time,
)


class TestStatePersistence(StatePersistenceTestCase):
    async def test_memory_compression_audit(self):
        """Verify that dialogue is compressed and early turns summarized when exceeding max_turns + 2."""
        self.manager.config.enable_memory_compression = True
        self.manager.config.max_memory_turns = 4

        # Mock agent's own client to return the summary text when requested
        async def mock_agent_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if "Summarize the preceding execution logs" in str(prompt):
                return "This is a summary of early task executions."
            return 'Thought: We are doing the task.\nFinal Answer: Task complete!'
        self.mock_react_client.generate = mock_agent_generate

        agent = Agent(name="Compressed_Agent", role="Summarizer", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing compression"
        )
        team.members.append(agent)

        agent.messages = [
            {"role": "system", "content": "Initial System Instructions"},
            {"role": "user", "content": "Turn 1 request"},
            {"role": "assistant", "content": "Turn 1 answer"},
            {"role": "user", "content": "Turn 2 request"},
            {"role": "assistant", "content": "Turn 2 answer"},
            {"role": "user", "content": "Turn 3 request"},
            {"role": "assistant", "content": "Turn 3 answer"},
        ]

        await team.execute_react_step(agent, "Turn 4 request", "Sys instructions")

        system_archives = [m for m in agent.messages if "*** HISTORICAL SUMMARY ARCHIVE ***" in m.get("content", "")]
        self.assertEqual(len(system_archives), 1)
        self.assertIn("This is a summary of early task executions.", system_archives[0]["content"])
        self.assertEqual(agent.messages[0]["content"], "Initial System Instructions")

    async def test_memory_compression_prevents_tool_splitting(self):
        """Verify that memory compression slice does not split tool calls and responses."""
        self.manager.config.enable_memory_compression = True
        self.manager.config.max_memory_turns = 4

        async def mock_agent_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if "Summarize the preceding execution logs" in str(prompt):
                return "This is a summary of early task executions."
            return 'Thought: We are doing the task.\nFinal Answer: Task complete!'
        self.mock_react_client.generate = mock_agent_generate

        agent = Agent(name="Compressed_Agent", role="Summarizer", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing compression"
        )
        team.members.append(agent)

        agent.messages = [
            {"role": "system", "content": "Initial System Instructions"},
            {"role": "user", "content": "Turn 1 request"},
            {"role": "assistant", "content": "Turn 1 answer"},
            {"role": "user", "content": "Turn 2 request"},
            {"role": "assistant", "content": "Turn 2 answer", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "File content"},
            {"role": "assistant", "content": "Turn 3 answer"},
            {"role": "user", "content": "Turn 4 request"},
        ]

        await team.execute_react_step(agent, "Turn 5 request", "Sys instructions")

        self.assertEqual(agent.messages[2]["role"], "assistant")
        self.assertIn("tool_calls", agent.messages[2])
        self.assertEqual(agent.messages[3]["role"], "tool")
        self.assertEqual(agent.messages[3]["tool_call_id"], "call_1")

