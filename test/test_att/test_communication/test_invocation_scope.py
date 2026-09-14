import json
import shutil
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse


class ScriptedPeerClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])

    def supports_native_tool_calling(self):
        return False

    async def generate(self, require_json=False, **kwargs):
        if require_json:
            return LLMResponse(
                text=json.dumps(
                    {"is_healthy": True, "reason": "healthy"}
                )
            )
        response = (
            self.responses.pop(0)
            if self.responses
            else "Final Answer: done"
        )
        return LLMResponse(text=response)


class TestPeerInvocationScope(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.mkdtemp(prefix="att-peer-invocation-")
        self.managers = []

    async def asyncTearDown(self):
        for manager in reversed(self.managers):
            await manager.close()
        shutil.rmtree(self.workspace, ignore_errors=True)

    def create_manager(self):
        root_client = ScriptedPeerClient()
        manager = ATTManager(
            Agent("Root", "Architect", root_client),
            ATTConfig(
                workspace_root=self.workspace,
                enable_memory_compression=False,
                llm_max_retries=0,
            ),
        )
        manager.register_llm_client("root", root_client)
        self.managers.append(manager)
        return manager

    async def _run_two_round_delivery(self, messages):
        manager = self.create_manager()
        messenger_client = ScriptedPeerClient()
        messenger = Agent("Messenger", "Researcher", messenger_client)
        manager.register_llm_client("messenger", messenger_client)
        manager.register_agent(messenger)
        sender = manager.bootstrap_agent_team(
            manager.root_ai,
            existing_members=[messenger],
            member_configs={"HelperA": {}, "HelperB": {}},
        )
        recipient = manager.create_agent_team(manager.root_ai)
        for message in messages:
            messenger_client.responses.extend(
                [
                    "Action: send_peer_message("
                    f"team_id={recipient.team_id!r}, message={message!r})",
                    "Final Answer: done",
                ]
            )

        await manager.execute_team_discussion(
            sender,
            "Send one update in every round.",
            rounds=2,
            skip_audit=True,
        )
        return [
            message.content
            for message in manager.broker.peer_messages.values()
        ]

    async def test_distinct_agent_turns_have_distinct_delivery_identity(self):
        delivered = await self._run_two_round_delivery(
            ["First update", "Second update"]
        )
        self.assertEqual(delivered, ["First update", "Second update"])

    async def test_identical_messages_in_distinct_turns_are_both_delivered(self):
        delivered = await self._run_two_round_delivery(
            ["Same update", "Same update"]
        )
        self.assertEqual(delivered, ["Same update", "Same update"])
