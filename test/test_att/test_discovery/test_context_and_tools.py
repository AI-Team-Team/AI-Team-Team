"""Normal model paths discover explicitly without automatic global directories."""

import asyncio
import json
import unittest
from unittest.mock import patch

from ai_team_team import (
    LLMResponse,
    ParentApprovalCommunicationConfig,
    TeamFormationDraft,
    ToolCall,
    ToolResultStatus,
)
from ai_team_team.core.tool_runtime import ToolExecutor

from ._fixture import DiscoveryFixture


class DiscoveryContextTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_text_native_and_personal_contexts_keep_identity_without_global_injection(self):
        outsider = self.person("UNDISCOVERED_AGENT_MARKER", description="Unrelated public role")
        distant = self.manager.create_agent_team(self.root, team_purpose="UNDISCOVERED_TEAM_MARKER")
        team = self.manager.create_agent_team(self.root, team_purpose="Current work")
        member = team.members[0]
        member.system_instructions = "CONTINUING_MEMBER_MISSION"
        member.append_message({"role": "assistant", "content": "CONTINUING_MEMBER_MEMORY"})
        for mode in ("text_react", "native"):
            self.manager.config.tool_calling_mode = mode
            start = len(self.client.calls)
            result = await self.manager.execute_agent_interaction(
                member, "Continue working.", team=team
            )
            personal = await self.manager.execute_agent_interaction(
                self.root, "Consider your work."
            )
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(personal.status.value, "completed")
            for call in self.client.calls[start:]:
                rendered = json.dumps(call)
                self.assertNotIn(outsider.name, rendered)
                self.assertNotIn(outsider.agent_id, rendered)
                self.assertNotIn(distant.team_id, rendered)
                self.assertNotIn("UNDISCOVERED_TEAM_MARKER", rendered)
                self.assertNotIn("ACTIVE AGENT TEAMS TOPOLOGY", rendered)
                self.assertNotIn("ACTIVE REGISTERED AGENTS AVAILABLE FOR MEMBERSHIP", rendered)
                for name in ("list_entities", "search_entities", "inspect_entity"):
                    self.assertIn(name, rendered)
            ordinary = self.client.calls[start]
            self.assertIn("CONTINUING_MEMBER_MISSION", ordinary["system_instruction"])
            self.assertIn("CONTINUING_MEMBER_MEMORY", str(ordinary["prompt"]))
            self.assertIn(team.team_id, ordinary["system_instruction"])
            self.assertIn(member.agent_id, ordinary["system_instruction"])
            self.assertEqual(member.system_instructions, "CONTINUING_MEMBER_MISSION")
        self.assertIn(distant.team_id, self.manager.render_topology_tree())

    async def test_text_and_native_can_explicitly_discover_and_remember_public_results(self):
        outsider = self.person("DiscoveredPerson", description="Database research")
        for mode in ("text_react", "native"):
            self.manager.config.tool_calling_mode = mode
            turn_calls = 0

            def response(prompt, **kwargs):
                nonlocal turn_calls
                turn_calls += 1
                if turn_calls == 1:
                    if mode == "native":
                        return LLMResponse(
                            tool_calls=[
                                ToolCall(
                                    call_id=f"discover-{mode}",
                                    name="search_entities",
                                    arguments={"keywords": ["DATABASE"], "entity_type": "agent"},
                                )
                            ]
                        )
                    return LLMResponse(
                        text="Action: search_entities(keywords=['DATABASE'], entity_type='agent')"
                    )
                return LLMResponse(text="Final Answer: I found a possible collaborator.")

            self.client.response = response
            start = len(self.client.calls)
            result = await self.manager.execute_agent_interaction(self.root, "Find a collaborator.")
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(turn_calls, 2)
            self.assertIn(outsider.agent_id, str(self.client.calls[start + 1]["prompt"]))
            self.assertIn(outsider.agent_id, str(self.root.message_history))
        self.assertEqual(len(self.manager.teams), 0)
        self.assertIsNone(self.manager._active_team.get())

    async def test_formation_deliberation_does_not_reinject_a_global_candidate_list(self):
        outsider = self.person("UNDISCOVERED_FORMATION_CANDIDATE")
        draft = TeamFormationDraft(
            draft_id="TFDRAFT-discovery-test",
            initiator_agent_id=self.root.agent_id,
            creator_kind="agent",
            creator_id=self.root.agent_id,
            objective="Find collaborators for a research proposal.",
            created_at=1.0,
            updated_at=1.0,
        )
        prompt = self.manager._formations._draft_deliberation_prompt(draft, None)
        self.assertNotIn(outsider.agent_id, prompt)
        self.assertNotIn(outsider.name, prompt)
        self.assertIn("entity-discovery tools", prompt)
        self.assertIn("membership consent", prompt)
        explicit = self.manager._formations._draft_deliberation_prompt(
            draft, {"invitee_agent_ids": [outsider.agent_id]}
        )
        self.assertIn(outsider.agent_id, explicit)

    async def test_default_context_size_does_not_grow_with_unrelated_registered_people(self):
        from ai_team_team.core.strategies.shared import _prepare_agent_context

        async with self.manager.agent_invocation(self.root):
            first = await _prepare_agent_context(None, self.root, "Do a small task.", self.manager)
        for index in range(100):
            self.person(f"Unrelated{index:03}", description="Long public description " * 20)
        async with self.manager.agent_invocation(self.root):
            second = await _prepare_agent_context(None, self.root, "Do a small task.", self.manager)
        self.assertEqual(first, second)
        self.assertEqual(len(self.manager.list_entities("agent", end_index=999).items), 101)

    async def test_discovery_tools_remain_available_when_delegation_or_advanced_memory_is_disabled(
        self,
    ):
        team = self.manager.create_agent_team(self.root)
        names = {"list_entities", "search_entities", "inspect_entity"}
        self.manager.config.enable_dynamic_delegation = False
        self.manager.config.episodic_memory.enabled = False
        self.assertTrue(names <= self.manager.get_available_tools(team).keys())
        self.assertTrue(names <= self.manager.get_available_tools(None, self.root).keys())
        self.manager.config.enable_dynamic_delegation = True
        self.manager.config.max_delegation_depth = team.depth
        self.assertTrue(names <= self.manager.get_available_tools(team).keys())
        self.assertNotIn("dispatch_subagent", self.manager.get_available_tools(team))

    async def test_tool_schemas_and_classification_forbid_unsupported_arguments(self):
        tools = self.manager.get_available_tools(None, self.root)
        executor = ToolExecutor(None, self.root, self.manager)
        properties = tools["list_entities"].json_schema["properties"]
        self.assertEqual(properties["entity_type"]["enum"], ["agent", "agent_team", "all"])
        self.assertEqual(properties["start_index"]["minimum"], 1)
        self.assertEqual(
            tools["search_entities"].json_schema["properties"]["keywords"]["minItems"], 1
        )
        for arguments in (
            {"cursor": "unused"},
            {"mode": "cursor"},
            {"agent_id": self.root.agent_id},
            {"start_index": True},
            {"start_index": "1"},
            {"start_index": 1.5},
            {"start_index": 3, "end_index": 2},
        ):
            result = await executor.execute("list_entities", kwargs=arguments, tools=tools)
            self.assertIs(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        for keywords in ([], [" "], ["valid", ""]):
            result = await executor.execute(
                "search_entities", kwargs={"keywords": keywords}, tools=tools
            )
            self.assertIs(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        result = await executor.execute(
            "inspect_entity", kwargs={"entity_type": "agent", "entity_id": "unknown"}, tools=tools
        )
        self.assertIs(result.status, ToolResultStatus.BUSINESS_ERROR)

    async def test_live_state_is_captured_on_the_event_loop_not_from_a_tool_worker(self):
        tools = self.manager.get_available_tools(None, self.root)
        loop = asyncio.get_running_loop()
        capture = self.manager._discovery._capture

        def checked_capture(*args):
            self.assertIs(asyncio.get_running_loop(), loop)
            return capture(*args)

        token = self.manager._active_tool_agent.set(self.root)
        try:
            with patch.object(self.manager._discovery, "_capture", side_effect=checked_capture):
                await asyncio.gather(
                    tools["list_entities"].invoke(),
                    tools["search_entities"].invoke(keywords=[self.root.name]),
                    tools["inspect_entity"].invoke(
                        entity_type="agent", entity_id=self.root.agent_id
                    ),
                )
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_governance_mail_uses_on_demand_discovery_without_an_automatic_directory(self):
        outsider = self.person("UNRELATED_GOVERNANCE_PERSON")
        self.manager.create_agent_team(self.root, team_purpose="UNRELATED_GOVERNANCE_TEAM")
        self.manager.config.communication = ParentApprovalCommunicationConfig()
        for mode in ("text_react", "native"):
            self.manager.config.tool_calling_mode = mode
            first = self.manager.create_agent_team(self.root)
            second = self.manager.create_agent_team(self.root)
            start = len(self.client.calls)
            request = await self.manager.broker.request_peer_communication(
                first, second, first.members[0].agent_id, "Consider this public channel."
            )
            async with asyncio.timeout(5):
                while self.manager._emergency_tasks:
                    await asyncio.gather(*tuple(self.manager._emergency_tasks))
                    await asyncio.sleep(0)
            calls = self.client.calls[start:]
            self.assertTrue(calls)
            rendered = json.dumps(calls)
            self.assertIn("governance voting email", rendered)
            self.assertIn("CONTINUING_PERSONAL_MISSION", rendered)
            self.assertNotIn(outsider.name, rendered)
            self.assertNotIn(outsider.agent_id, rendered)
            self.assertNotIn("UNRELATED_GOVERNANCE_TEAM", rendered)
            for name in ("list_entities", "search_entities", "inspect_entity"):
                self.assertIn(name, rendered)
            self.assertEqual(
                self.manager.broker.communication_requests[request.request_id].status.value,
                "PENDING",
            )

    async def test_removing_automatic_injection_does_not_erase_previously_learned_directory_info(
        self,
    ):
        known = self.person("PreviouslyDiscoveredPerson")
        learned = f"Earlier discovery: {known.name} has stable ID {known.agent_id}."
        self.root.append_message({"role": "assistant", "content": learned})
        result = await self.manager.execute_agent_interaction(self.root, "Continue your work.")
        self.assertEqual(result.status.value, "completed")
        self.assertIn(learned, str(self.client.calls[-1]["prompt"]))
        self.assertIn(learned, str(self.root.messages))
        self.assertIn(learned, str(self.root.message_history))
        self.assertNotIn(known.agent_id, self.client.calls[-1]["system_instruction"])
