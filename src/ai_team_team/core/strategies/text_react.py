"""Strict text ReAct reasoning strategy."""

import re
from typing import Any, List

from ai_team_team.core.agent import Agent
from ai_team_team.core.exceptions import ToolArgumentError
from ai_team_team.core.response import (
    AgentTurnResult,
    LLMResponse,
    ToolFailureSummary,
    ToolResult,
    ToolResultStatus,
)
from ai_team_team.core.text_action import parse_text_action, parse_tool_arguments
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.tool import render_tool_prompt

from .base import BaseReasoningStrategy
from .shared import (
    _MEMORY_RECALL_TOOL_NAMES,
    _MEMORY_WINDOW_MARKER,
    _PRIVATE_TOOL_NAMES,
    _append_agent_message,
    _append_private_window_message,
    _append_transient_window_message,
    _available_tools,
    _extract_final_answer,
    _memory_recall_placeholder,
    _prepare_agent_context,
    _privacy_safe_agent_output,
    _record_tool_result,
    _redact_private_log,
    _scrub_private_window_messages,
    _turn_result,
)


class TextReactReasoningStrategy(BaseReasoningStrategy):
    """Strict text ReAct loop backed by the shared tool runtime."""

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
        argument_failures = 0
        try:
            identity_header = await _prepare_agent_context(
                team, agent, prompt, manager
            )
            tools = _available_tools(team, agent, manager)
            if not tools:
                agent_mission = (
                    f"\n\n### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}"
                    if getattr(agent, "system_instructions", "")
                    else ""
                )
                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=agent.messages,
                    system_instruction=(
                        f"{system_instruction}{agent_mission}\n\n{identity_header}\n"
                        "Output exactly 'Final Answer: <content>' when complete."
                    ),
                    temperature=0.3,
                    retries=manager.config.llm_max_retries if manager else 3,
                    backoff_factor=(
                        manager.config.llm_retry_backoff_factor
                        if manager
                        else 1.5
                    ),
                    manager=manager,
                )
                text = response.text if isinstance(response, LLMResponse) else str(response)
                answer = _extract_final_answer(text)
                if answer is None:
                    answer = text.strip()
                _append_agent_message(
                    agent,
                    {"role": "assistant", "content": answer},
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
                return _turn_result(team, agent, manager, answer=answer)

            rendered_tools = []
            for name, tool in tools.items():
                mode = (
                    manager.config.tool_prompt_modes.get(name)
                    if manager
                    else None
                ) or tool.prompt_schema_mode or (
                    manager.config.text_tool_schema_mode
                    if manager
                    else "compact"
                )
                rendered_tools.append(render_tool_prompt(tool, mode))
            react_instruction = (
                f"{system_instruction}\n\n"
                + (
                    f"### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}\n\n"
                    if getattr(agent, "system_instructions", "")
                    else ""
                )
                + f"{identity_header}"
                "### AVAILABLE TOOLS\n"
                + "\n".join(rendered_tools)
                + "\n\n### REACT FORMAT INSTRUCTIONS\n"
                "Use exactly one Action per response when invoking a tool.\n"
                "Thought: <brief reasoning>\n"
                "Action: tool_name(<literal positional or keyword arguments>)\n"
                "When complete, output exactly Final Answer: <content>."
            )
            executor = ToolExecutor(team, agent, manager)
            max_argument_retries = (
                manager.config.max_tool_argument_retries if manager else 3
            )
            for step in range(max_steps):
                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=agent.messages,
                    system_instruction=react_instruction,
                    temperature=0.3,
                    retries=manager.config.llm_max_retries if manager else 3,
                    backoff_factor=(
                        manager.config.llm_retry_backoff_factor
                        if manager
                        else 1.5
                    ),
                    manager=manager,
                )
                text = response.text if isinstance(response, LLMResponse) else str(response)
                text = text.strip()
                has_action = bool(
                    re.search(r"(?im)^\s*Action\s*:", text)
                    or re.search(r"<action\s+name=", text, re.IGNORECASE)
                )
                stored_text = _privacy_safe_agent_output(agent, text)
                if has_action:
                    stored_text = _redact_private_log(stored_text)
                _append_agent_message(
                    agent,
                    {
                        "role": "assistant",
                        "content": stored_text,
                    },
                    team,
                    manager,
                    capture_content=not has_action,
                )
                answer = _extract_final_answer(text)
                if answer is not None:
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

                try:
                    action = parse_text_action(text)
                    args, kwargs = parse_tool_arguments(action.arguments)
                    call_id = (
                        f"{manager._active_discussion_id.get() or 'runtime'}:"
                        f"{agent.agent_id}:{step}:{action.name}"
                        if manager
                        else f"{agent.agent_id}:{step}:{action.name}"
                    )
                    result = await executor.execute(
                        action.name,
                        args,
                        kwargs,
                        call_id=call_id,
                        tools=tools,
                    )
                    if manager:
                        manager._emit_callback(
                            "on_activity_added",
                            agent.name,
                            "Action",
                            f"{action.name}(...)"
                        )
                except ToolArgumentError as exc:
                    result = ToolResult(
                        f"{agent.agent_id}:{step}:parse",
                        "<action>",
                        str(exc),
                        status=ToolResultStatus.INVALID_ARGUMENTS,
                        error_kind="action_parse",
                    )

                _record_tool_result(manager, team, agent, result)

                summary = result.failure_summary()
                if summary is not None:
                    failures.append(summary)
                observation = {
                    "role": "user",
                    "content": (
                        f"Observation [{result.status.value}]: {result.content}"
                    ),
                    "tool_status": result.status.value,
                    "tool_error_kind": result.error_kind,
                    "tool_attempts": result.attempts,
                }
                if result.name in _PRIVATE_TOOL_NAMES:
                    _append_private_window_message(
                        agent, observation, team, manager
                    )
                elif result.name in _MEMORY_RECALL_TOOL_NAMES:
                    _append_transient_window_message(
                        agent,
                        observation,
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
                        observation,
                        team,
                        manager,
                        capture_content=capture,
                    )
                if manager:
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
                    argument_failures += 1
                    if argument_failures > max_argument_retries:
                        return _turn_result(
                            team,
                            agent,
                            manager,
                            error_kind="tool_argument_retries_exhausted",
                            reason=(
                                "Tool arguments remained invalid after "
                                f"{argument_failures} attempts."
                            ),
                            failures=failures,
                        )
                elif result.status in {
                    ToolResultStatus.TRANSIENT_ERROR,
                    ToolResultStatus.INTERNAL_ERROR,
                }:
                    return _turn_result(
                        team,
                        agent,
                        manager,
                        error_kind=result.error_kind or result.status.value,
                        reason=(
                            f"Tool {result.name!r} did not complete after "
                            f"{result.attempts} attempt(s) with "
                            f"{result.status.value}."
                        ),
                        failures=failures,
                    )
            return _turn_result(
                team,
                agent,
                manager,
                error_kind="reasoning_step_limit",
                reason=(
                    "Text ReAct reached its step limit without a final answer."
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

