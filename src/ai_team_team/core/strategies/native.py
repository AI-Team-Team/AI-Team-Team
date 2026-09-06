"""Native provider tool-calling reasoning strategy."""

import asyncio
from typing import Any, List

from ai_team_team.core.agent import Agent
from ai_team_team.core.response import (
    AgentTurnResult,
    LLMResponse,
    ToolFailureSummary,
    ToolResult,
    ToolResultStatus,
)
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.core.utils import generate_with_retry

from .base import BaseReasoningStrategy
from .shared import (
    _MEMORY_RECALL_TOOL_NAMES,
    _MEMORY_WINDOW_MARKER,
    _PRIVATE_TOOL_NAMES,
    _append_agent_message,
    _append_private_window_message,
    _append_transient_window_message,
    _available_tools,
    _memory_recall_placeholder,
    _prepare_agent_context,
    _privacy_safe_agent_output,
    _record_tool_result,
    _redact_private_tool_calls,
    _scrub_private_window_messages,
    _turn_result,
)


class NativeReasoningStrategy(BaseReasoningStrategy):
    """Native parallel tool loop backed by the shared tool runtime."""

    async def execute(
        self,
        team: Any,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int,
        manager: Any,
    ) -> AgentTurnResult:
        failures: List[ToolFailureSummary] = []
        argument_failure_rounds = 0
        try:
            identity_header = await _prepare_agent_context(
                team, agent, prompt, manager
            )
            tools = _available_tools(team, agent, manager)
            native_tools = list(tools.values())
            executor = ToolExecutor(team, agent, manager)
            max_rounds = manager.config.max_tool_rounds if manager else 5
            max_argument_retries = (
                manager.config.max_tool_argument_retries if manager else 3
            )
            for round_index in range(max_rounds):
                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=agent.messages,
                    system_instruction=f"{system_instruction}\n\n{identity_header}",
                    temperature=0.3,
                    require_json=False,
                    retries=manager.config.llm_max_retries if manager else 3,
                    backoff_factor=(
                        manager.config.llm_retry_backoff_factor
                        if manager
                        else 1.5
                    ),
                    tools=native_tools or None,
                    return_response_obj=True,
                    manager=manager,
                )
                if isinstance(response, str):
                    response = LLMResponse(text=response)
                if not response.tool_calls:
                    answer = response.text or ""
                    _append_agent_message(
                        agent,
                        {
                            "role": "assistant",
                            "content": _privacy_safe_agent_output(agent, answer),
                        },
                        team,
                        manager,
                    )
                    if manager:
                        manager._emit_callback(
                            "on_activity_added",
                            agent.name,
                            "Final Answer",
                            _privacy_safe_agent_output(agent, answer),
                        )
                    return _turn_result(
                        team, agent, manager, answer=answer, failures=failures
                    )

                _append_agent_message(
                    agent,
                    {
                        "role": "assistant",
                        "content": (
                            "[private tool payload redacted]"
                            if any(
                                call.name in _PRIVATE_TOOL_NAMES
                                for call in response.tool_calls
                            )
                            else _privacy_safe_agent_output(
                                agent, response.text or ""
                            )
                        ),
                        "tool_calls": _redact_private_tool_calls(
                            [call.to_dict() for call in response.tool_calls]
                        ),
                    },
                    team,
                    manager,
                    capture_content=False,
                )
                results = await asyncio.gather(
                    *(
                        executor.execute(
                            call.name,
                            kwargs=(
                                call.arguments
                                if isinstance(call.arguments, dict)
                                else {}
                            ),
                            call_id=call.call_id,
                            raw=call.raw,
                            tools=tools,
                        )
                        if isinstance(call.arguments, dict)
                        else asyncio.sleep(
                            0,
                            result=ToolResult(
                                call.call_id,
                                call.name,
                                "Native tool arguments must be an object.",
                                call.raw,
                                status=ToolResultStatus.INVALID_ARGUMENTS,
                                error_kind="native_arguments_not_object",
                            ),
                        )
                        for call in response.tool_calls
                    )
                )
                invalid_batch = False
                fatal_tool_result = None
                for result in results:
                    _record_tool_result(manager, team, agent, result)
                    summary = result.failure_summary()
                    if summary is not None:
                        failures.append(summary)
                    message = {
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "name": result.name,
                        "content": (
                            f"[{result.status.value}] {result.content}"
                        ),
                        "tool_status": result.status.value,
                        "tool_error_kind": result.error_kind,
                        "tool_attempts": result.attempts,
                    }
                    if result.name in _PRIVATE_TOOL_NAMES:
                        _append_private_window_message(
                            agent, message, team, manager
                        )
                    elif result.name in _MEMORY_RECALL_TOOL_NAMES:
                        _append_transient_window_message(
                            agent,
                            message,
                            team,
                            manager,
                            marker=_MEMORY_WINDOW_MARKER,
                            placeholder=_memory_recall_placeholder(result),
                        )
                    else:
                        tool = tools.get(result.name)
                        capture = bool(
                            tool is not None and tool.memory_capture == "content"
                        )
                        _append_agent_message(
                            agent,
                            message,
                            team,
                            manager,
                            capture_content=capture,
                        )
                    if manager:
                        manager._emit_callback(
                            "on_activity_added",
                            agent.name,
                            "Action",
                            f"{result.name}(id={result.tool_call_id})",
                        )
                        manager._emit_callback(
                            "on_activity_added",
                            agent.name,
                            "Observation",
                            (
                                "[private tool result redacted]"
                                if result.name in _PRIVATE_TOOL_NAMES
                                else (
                                    f"{result.name}: {result.status.value}"
                                )
                            ),
                        )
                    if result.status in {
                        ToolResultStatus.INVALID_ARGUMENTS,
                        ToolResultStatus.UNKNOWN_TOOL,
                    }:
                        invalid_batch = True
                    elif result.status in {
                        ToolResultStatus.TRANSIENT_ERROR,
                        ToolResultStatus.INTERNAL_ERROR,
                    }:
                        fatal_tool_result = fatal_tool_result or result
                if fatal_tool_result is not None:
                    return _turn_result(
                        team,
                        agent,
                        manager,
                        error_kind=(
                            fatal_tool_result.error_kind
                            or fatal_tool_result.status.value
                        ),
                        reason=(
                            f"Tool {fatal_tool_result.name!r} did not complete "
                            f"after {fatal_tool_result.attempts} attempt(s): "
                            f"{fatal_tool_result.status.value}."
                        ),
                        failures=failures,
                    )
                if invalid_batch:
                    argument_failure_rounds += 1
                    if argument_failure_rounds > max_argument_retries:
                        return _turn_result(
                            team,
                            agent,
                            manager,
                            error_kind="tool_argument_retries_exhausted",
                            reason=(
                                "Native tool arguments remained invalid after "
                                f"{argument_failure_rounds} tool rounds."
                            ),
                            failures=failures,
                        )
            return _turn_result(
                team,
                agent,
                manager,
                error_kind="reasoning_round_limit",
                reason=(
                    "Native tool calling reached its round limit without a "
                    "final answer."
                ),
                failures=failures,
            )
        finally:
            _scrub_private_window_messages(agent)
            team.set_status(agent.name, "Idle")
            if manager:
                manager._emit_callback("on_status_change", agent.name, "Idle")
                manager._auto_save(
                    agents={agent.agent_id}, teams={team.team_id}
                )
