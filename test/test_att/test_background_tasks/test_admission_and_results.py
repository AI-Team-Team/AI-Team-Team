"""Accepted executions own their inputs and return only owner-authorized results."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, ExecutionConfig, StatePersistenceError, ToolArgumentError, ToolPermissionError
from ai_team_team.core.activity.contracts import AgentTeamScope

from ._support import BackgroundTestCase, contract


class AdmissionTests(BackgroundTestCase):
    async def test_explicit_admission_has_no_fake_personal_invocation(self):
        seen = []

        async def operation(value: str) -> str:
            seen.append((value, self.manager._activity.current.get(), self.manager._active_tool_agent.get()))
            return "RESULT-" + value

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation", {"value": "one"}, description="Personal task", labels=("research",))
        await self.finish(handle)
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(view.execution_state, "completed")
        self.assertEqual(view.attention_state, "required")
        self.assertEqual(view.description, "Personal task")
        self.assertEqual(view.labels, ("research",))
        self.assertEqual(seen, [("one", None, self.root)])
        self.assertFalse(self.records("activity_invocations"))
        self.assertEqual(len(self.records("execution_attempts")), 1)
        self.assertEqual(len(self.records("execution_payloads")), 2)
        result = await self.manager.read_background_task_result(handle.execution_id, actor=self.root, character_count=4)
        self.assertEqual(result.content, "RESU")
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).attention_state, "required")
        await self.manager.acknowledge_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "completed")
        self.assertEqual(self.manager.list_background_tasks(actor=self.root).total_count, 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)

    async def test_invalid_unknown_and_foreground_only_tools_never_dispatch(self):
        invoked = []

        def operation(value: str) -> str:
            invoked.append(value)
            return value

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        self.manager.register_tool("undeclared", func=operation)
        for name in ("undeclared", "missing", "keep_memory_in_context"):
            with self.assertRaises(ToolPermissionError):
                await self.start(name, {"value": "never"})
        with self.assertRaises(ToolArgumentError):
            await self.start("operation", {"value": ["wrong"]})
        self.assertFalse(invoked)
        self.assertFalse(self.records("executions"))

    async def test_auditor_denial_is_not_an_execution_attempt(self):
        invoked = []

        def operation() -> str:
            invoked.append(True)
            return "never"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        self.manager.register_tool_auditor("operation", lambda: (False, "Not permitted"))
        handle = await self.start("operation")
        await self.finish(handle)
        self.assertFalse(invoked)
        self.assertFalse(self.records("execution_attempts"))
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "failed")

    async def test_other_owner_cannot_inspect_search_read_or_cancel(self):
        other = Agent("Other", "Researcher", self.client)
        self.manager.register_agent(other)

        async def operation() -> str:
            return "PRIVATE_RESULT"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await self.finish(handle)
        self.assertEqual(self.manager.list_background_tasks(actor=other).total_count, 0)
        with self.assertRaises(PermissionError):
            self.manager.inspect_background_task(handle.execution_id, actor=other)
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=other)
        with self.assertRaises(PermissionError):
            await self.manager.cancel_background_task(handle.execution_id, actor=other)

    async def test_rejected_admission_does_not_dispatch(self):
        invoked = []

        async def operation() -> str:
            invoked.append(True)
            return "never"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("rejected")):
            with self.assertRaises(StatePersistenceError):
                await self.start("operation")
        self.assertFalse(invoked)
        self.assertFalse(self.manager._executions.jobs)
        self.assertFalse(self.records("executions"))

    def test_configuration_validates_construction_and_assignment(self):
        from pydantic import ValidationError
        for values in ({"automatic_detachment_seconds": 0}, {"max_concurrent_executions": -1},
                       {"retain_results_after_source_revocation": "true"}, {"cancellation_grace_seconds": float("inf")}):
            with self.assertRaises(ValidationError):
                ExecutionConfig(**values)
        with self.assertRaises(ValidationError):
            self.manager.config.executions.retain_results_after_source_revocation = 1

    async def test_tool_result_metadata_never_automatically_publishes_output(self):
        events = []
        self.manager.on_system_event = lambda *args: events.append(args)

        async def operation(secret: str) -> str:
            return secret

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation", {"secret": "SENSITIVE_BODY"})
        await self.finish(handle)
        await self.manager.flush_callbacks()
        self.assertNotIn("SENSITIVE_BODY", str(events))
        self.assertNotIn("SENSITIVE_BODY", self.manager.list_background_tasks(actor=self.root).model_dump_json())
        self.assertNotIn("SENSITIVE_BODY", self.manager._executions.summary(self.root))
        self.assertFalse(self.records("chat_messages"))
        self.assertNotIn("SENSITIVE_BODY", str(self.root.message_history))
