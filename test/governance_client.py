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
            tasks = tuple(manager._institutional_tasks | activity.workers | activity.dispatch_tasks)
            if tasks:
                results = await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)
                for task, result in zip(tasks, results):
                    if isinstance(result, asyncio.CancelledError) and task.get_name().startswith(("att-resource-deadline:", "att-resource-prepare:", "att-resource-apply:")):
                        continue
                    if isinstance(result, BaseException):
                        raise result
            elif activity.ready.empty():
                for session in activity.sessions.values():
                    if session.failure is not None:
                        raise session.failure
                return
            await asyncio.sleep(0)


async def submit_case_ballots(manager, case, *, approved=True, model_alias=None):
    """Submit explicit fixtures as each frozen voter, never infer a team choice."""
    for owner in case.voter_agent_ids:
        actor = manager._agents_by_id[owner]
        token = manager._active_tool_agent.set(actor)
        try:
            choice = {"approved": approved} if case.choice_kind == "boolean" else {"model_alias": model_alias or case.candidates[0]}
            await manager.submit_governance_choice(case.case_id, choice, actor=actor)
        finally:
            manager._active_tool_agent.reset(token)


async def approve_pending_business(manager, business_id):
    await settle_governance_activity(manager)
    for case in tuple(manager._governance.cases.values()):
        if case.business_id == business_id and case.status == "PENDING":
            await submit_case_ballots(manager, case)
    await settle_governance_activity(manager)


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
                {"case_id": item["case_id"], "choice": choice},
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
