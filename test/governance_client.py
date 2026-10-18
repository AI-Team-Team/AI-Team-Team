"""Deterministic clients that voluntarily open email and submit actual tool choices."""

import json
import re
import asyncio

from ai_team_team import LLMResponse, ToolCall
from test.async_waits import DEFAULT_RUNTIME_TIMEOUT, runtime_watchdog


async def settle_governance_activity(manager, timeout=DEFAULT_RUNTIME_TIMEOUT):
    """Observe scripted idle and committed domain work, not obsolete mail Tasks."""
    async with runtime_watchdog(manager, timeout=timeout, label="Governance activity settlement"):
        while True:
            activity = manager._activity
            tasks = tuple(manager._emergency_tasks | activity.workers | activity.dispatch_tasks)
            if tasks:
                await asyncio.gather(*(asyncio.shield(task) for task in tasks))
            elif activity.ready.empty():
                for session in activity.sessions.values():
                    if session.failure is not None:
                        raise session.failure
                return
            await asyncio.sleep(0)


def governance_action(prompt, *, approved=True, model_alias=None, native=False):
    """Produces tool calls only in response to a personal notice or opened email."""
    if not isinstance(prompt, list) or not prompt:
        return None
    content = prompt[-1].get("content") or ""
    match = re.search(r"You received a governance voting email `([^`]+)`", content)
    name = None
    if match:
        name, arguments = "open_agent_mail", {"message_id": match.group(1)}
    else:
        try:
            value = content.split(": ", 1)[1] if content.startswith("Observation [") else content
            if value.startswith("[success] "):
                value = value[len("[success] ") :]
            body = json.loads(value)
        except (ValueError, TypeError):
            return None
        if isinstance(body, dict) and "governance" in body:
            item = body["governance"]
            choice = (
                {"approved": approved, "reason": "Explicit personal choice."}
                if item["choice_kind"] == "boolean"
                else {
                    "model_alias": model_alias or item["candidates"][0],
                    "reason": "Explicit personal resource choice.",
                }
            )
            name, arguments = (
                "submit_governance_choice",
                {"round_id": item["round_id"], "choice": choice},
            )
    if name is None:
        return None
    if native:
        return LLMResponse(
            tool_calls=[ToolCall(call_id=f"test-{name}", name=name, arguments=arguments)]
        )
    return (
        "Action: "
        + name
        + "("
        + ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        + ")"
    )


class PersonalGovernanceClient:
    def __init__(self, approved=True, *, model_alias=None, native=False, respond=True):
        self.approved = approved
        self.model_alias = model_alias
        self.native = native
        self.respond = respond
        self.calls = []

    async def generate(self, prompt=None, system_instruction=None, require_json=False, **kwargs):
        self.calls.append((prompt, system_instruction, kwargs))
        if require_json:
            return '{"is_healthy": true, "reason": "healthy"}'
        if self.respond:
            action = governance_action(
                prompt, approved=self.approved, model_alias=self.model_alias, native=self.native
            )
            if action is not None:
                return action
        if "Activity continues by default." in (system_instruction or ""):
            return (LLMResponse(tool_calls=[ToolCall("choose-idle", "set_activity_intent", {"intent": {"kind": "idle"}})])
                    if self.native else "Action: set_activity_intent(intent={'kind': 'idle'})")
        return (
            LLMResponse(text="Discussion complete.") if self.native else "Final Answer: discussed"
        )

    def supports_native_tool_calling(self):
        return self.native

    def supports_output_token_limit(self):
        return True
