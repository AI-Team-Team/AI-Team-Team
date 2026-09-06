"""Shared context, privacy, and result helpers for reasoning strategies."""

import inspect
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_team_team.core.agent import Agent
from ai_team_team.core.response import (
    AgentTurnResult,
    AgentTurnStatus,
    LLMResponse,
    ToolFailureSummary,
    ToolResult,
)
from ai_team_team.core.text_action import parse_tool_arguments
from ai_team_team.core.utils import generate_with_retry

_PRIVATE_TOOL_NAMES = {
    "list_private_files",
    "read_private_file",
    "write_private_file",
    "delete_private_file",
    "move_private_file",
    "publish_private_file",
}
_PRIVATE_WINDOW_MARKER = "[ATT_PRIVATE_OBSERVATION]"
_MEMORY_RECALL_TOOL_NAMES = {"recall_memory"}
_MEMORY_WINDOW_MARKER = "[ATT_MEMORY_RECALL]"


def _memory_recall_placeholder(result: ToolResult) -> str:
    try:
        memory_id = json.loads(result.content).get("memory_id")
    except (AttributeError, TypeError, ValueError):
        memory_id = None
    return f"[Historical memory recalled: {memory_id or 'unknown'}]"


def _redact_private_log(text: Any) -> str:
    """Removes complete log payloads that mention private operations."""
    rendered = str(text)
    if (
        _PRIVATE_WINDOW_MARKER in rendered
        or any(name in rendered for name in _PRIVATE_TOOL_NAMES)
    ):
        return "[private tool payload redacted]"
    return rendered


def _private_action_metadata(
    tool_name: str, tool_obj: Any, args: List[Any], kwargs: Dict[str, Any]
) -> str:
    """Formats private operation metadata without file content."""
    try:
        bound = inspect.signature(tool_obj.func).bind_partial(*args, **kwargs)
        allowed = {
            key: value
            for key, value in bound.arguments.items()
            if key != "content"
        }
    except (TypeError, ValueError):
        allowed = {key: value for key, value in kwargs.items() if key != "content"}
    return f"{tool_name}({allowed!r})"


def _append_agent_message(
    agent: Agent,
    message: Dict[str, Any],
    team: Any,
    manager: Any,
    *,
    capture_content: bool = True,
) -> None:
    """Records a message with its invocation-scoped team and discussion."""
    enriched = dict(message)
    enriched["team_id"] = team.team_id
    discussion_id = (
        manager._active_discussion_id.get() if manager else None
    )
    enriched["discussion_id"] = discussion_id
    agent.append_message(enriched, capture_content=capture_content)


def _append_private_window_message(
    agent: Agent,
    message: Dict[str, Any],
    team: Any,
    manager: Any,
) -> None:
    """Keeps a private observation in the model window but not durable history."""
    _append_transient_window_message(
        agent,
        message,
        team,
        manager,
        marker=_PRIVATE_WINDOW_MARKER,
        placeholder="[private tool result redacted]",
    )


def _append_transient_window_message(
    agent: Agent,
    message: Dict[str, Any],
    team: Any,
    manager: Any,
    *,
    marker: str,
    placeholder: str,
) -> None:
    """Keeps one observation for this invocation without persisting its body."""
    actual = dict(message)
    actual["content"] = f"{marker}\n{actual.get('content', '')}"
    actual["team_id"] = team.team_id
    actual["discussion_id"] = (
        manager._active_discussion_id.get() if manager else None
    )
    persisted = dict(actual)
    persisted["content"] = placeholder
    agent.sync_message_history()
    agent.messages.append(actual)
    agent.message_history.append(persisted)
    agent._history_seen_ids.add(id(actual))
    if manager:
        manager._memory.record_message(
            agent,
            team,
            persisted,
            capture_content=False,
        )


def _has_private_window_content(agent: Agent) -> bool:
    """Returns whether the active model window contains private observations."""
    return any(
        _PRIVATE_WINDOW_MARKER in str(message.get("content", ""))
        for message in agent.messages
    )


def _privacy_safe_agent_output(agent: Agent, value: Any) -> str:
    """Redacts callback/log output derived from a private model window."""
    if _has_private_window_content(agent):
        return "[private-derived agent output redacted]"
    return _redact_private_log(value)


def _scrub_private_window_messages(agent: Agent) -> None:
    """Expires private and recalled-memory observations after the invocation."""
    for index, message in enumerate(agent.messages):
        content = str(message.get("content", ""))
        if _PRIVATE_WINDOW_MARKER in content:
            placeholder = "[private tool result redacted]"
        elif _MEMORY_WINDOW_MARKER in content:
            match = re.search(r'"memory_id"\s*:\s*"([^"]+)"', content)
            placeholder = (
                f"[Historical memory recalled: {match.group(1)}]"
                if match
                else "[Historical memory recalled: unknown]"
            )
        else:
            continue
        safe_message = dict(message)
        safe_message["content"] = placeholder
        agent._history_seen_ids.discard(id(message))
        agent._history_seen_ids.add(id(safe_message))
        agent.messages[index] = safe_message


def _redact_private_tool_calls(
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Removes private file bodies from structured assistant messages."""
    sanitized = []
    for tool_call in tool_calls:
        item = dict(tool_call)
        function = item.get("function")
        name = item.get("name")
        if isinstance(function, dict):
            name = function.get("name", name)
        if name in _PRIVATE_TOOL_NAMES:
            if isinstance(function, dict):
                safe_function = dict(function)
                safe_function["arguments"] = {"private_payload": "redacted"}
                item["function"] = safe_function
            if "arguments" in item:
                item["arguments"] = {"private_payload": "redacted"}
        sanitized.append(item)
    return sanitized


async def _prepare_agent_context(team: Any, agent: Agent, prompt: str, manager: Any) -> str:
    """Prepares the agent context, memory compression, transition notice, and returns the identity header."""
    team.set_status(agent.name, "Thinking...")
    if manager:
        manager._emit_callback("on_status_change", agent.name, "Thinking...")

    peer_context = ""
    if manager:
        peer_context = f"\n### ACTIVE AGENT TEAMS TOPOLOGY (Global Map)\n{manager.render_topology_tree()}\n"

    max_depth = manager.config.max_delegation_depth if manager else 2
    min_size = manager.config.min_subagent_team_size if manager else 3

    all_models = {}
    if manager:
        for k, v in manager.model_configs.items():
            all_models[k] = v.get("ai_note", "No description")
        for k in manager.llm_clients.keys():
            if k not in all_models:
                all_models[k] = "No description"

    model_options = "\n".join([f"  - {k}: {note}" for k, note in all_models.items()])
    role_desc_str = f"- **Role Description**: {agent.role_description}\n" if getattr(agent, "role_description", "") else ""
    experts_str = ""
    if manager:
        experts_lines = []
        for name, exp_agent in sorted(manager.agents.items()):
            role_desc = getattr(exp_agent, "role_description", "") or "No description"
            experts_lines.append(
                f"  - **{name}** (agent_id: `{exp_agent.agent_id}`; identity role: {exp_agent.role}): {role_desc}"
            )
        if experts_lines:
            experts_str = (
                "## ACTIVE REGISTERED AGENTS AVAILABLE FOR MEMBERSHIP\n"
                + "\n".join(experts_lines)
                + "\n\n"
            )

    visible_tools = (
        manager.get_available_tools(team, agent)
        if manager and hasattr(manager, "get_available_tools")
        else dict(getattr(team, "tools", {}) or {})
    )
    autonomy_lines = ["### AUTONOMY RULES"]
    if "dispatch_subagent" in visible_tools:
        autonomy_lines.append(
            "- You can dynamically spawn child ATs using the `dispatch_subagent` tool to solve sub-problems."
        )
    if "delegate_escalation" in visible_tools:
        autonomy_lines.append(
            "- You can use `delegate_escalation` to ask your parent AgentTeam for help."
        )
    autonomy_lines.extend(
        [
            f"- A valid AT MUST have at least {min_size} members.",
            "- You may use only the tools shown in the current AVAILABLE TOOLS section.",
            "- When creating an AT, choose only registered models. Available models:",
            model_options,
        ]
    )
    autonomy_text = "\n".join(autonomy_lines) + "\n"

    identity_header = (
        f"## AGENT IDENTITY PROFILE\n"
        f"- **Identity Role**: {agent.role}\n"
        f"{role_desc_str}"
        f"- **Agent Name**: {agent.name}\n"
        f"- **Current AgentTeam**: {team.team_id} (Preset: {team.preset_name})\n"
        f"- **Team Purpose**: {team.team_purpose}\n"
        f"- **Current Objective**: Cooperate in team tasks.\n"
        f"- **AT Delegation Depth**: {team.depth} / {max_depth}\n"
        f"{peer_context}"
        f"{experts_str}"
        f"{autonomy_text}"
    )
    if manager and manager.config.episodic_memory.enabled:
        identity_header += manager._memory.retained_context(agent.agent_id)

    current_context = {
        "team_id": team.team_id,
        "preset_name": team.preset_name,
        "team_purpose": team.team_purpose,
        "role": agent.role,
        "role_description": getattr(agent, "role_description", ""),
        "system_instructions": getattr(agent, "system_instructions", ""),
        "tools": sorted(visible_tools)
    }
    if agent.last_context and agent.last_context.get("team_id") != team.team_id:
        notice = (
            f"*** TRANSITION NOTICE: ACTIVE TEAM UPDATE ***\n"
            f"You have transitioned to work with another team group:\n"
            f"- Active Team: {team.team_id} (Preset: {team.preset_name})\n"
            f"- Team Purpose: {team.team_purpose}\n"
            f"- Your Identity Role: {agent.role}\n"
            f"Please continue your work and cooperate in this team based on your prior memory."
        )
        _append_agent_message(
            agent, {"role": "system", "content": notice}, team, manager
        )
    agent.last_context = current_context

    enable_compression = manager.config.enable_memory_compression if manager else True
    max_turns = manager.config.max_memory_turns if manager else 20

    if enable_compression and len(agent.messages) > max_turns + 2:
        first_msg = agent.messages[0]

        slice_idx = len(agent.messages) - max_turns
        while slice_idx > 1 and agent.messages[slice_idx].get("role") in ("tool", "function"):
            slice_idx -= 1

        intermediate_messages = agent.messages[1 : slice_idx]
        history_text_parts = []
        for msg in intermediate_messages:
            r = msg.get("role", "unknown").upper()
            c = msg.get("content", "")
            history_text_parts.append(f"{r}: {c}")
        history_text = _redact_private_log("\n".join(history_text_parts))

        summary_prompt = (
            f"Summarize the preceding execution logs and discussions into a single cohesive paragraph of historical facts. "
            f"Focus on what was completed.\n\n"
            f"--- EXECUTION LOGS AND DISCUSSIONS BEGIN ---\n"
            f"{history_text}\n"
            f"--- EXECUTION LOGS AND DISCUSSIONS END ---\n"
        )

        summarize_client = agent.llm_client
        retries = manager.config.llm_max_retries if manager else 3
        backoff = manager.config.llm_retry_backoff_factor if manager else 1.5

        try:
            summary_resp = await generate_with_retry(
                llm_client=summarize_client,
                prompt=summary_prompt,
                system_instruction="You are a precise summarization assistant.",
                temperature=0.3,
                retries=retries,
                backoff_factor=backoff,
                manager=manager
            )
            summary_text = summary_resp.text if isinstance(summary_resp, LLMResponse) else str(summary_resp)
            summary_text = summary_text.strip()
        except Exception as e:
            team.logger.warning(f"Memory compression summarization failed: {e}. Using a generic fallback summary.")
            summary_text = "Early execution history compressed due to context limits."

        archive_message = {
            "role": "system",
            "content": f"*** HISTORICAL SUMMARY ARCHIVE ***\n{summary_text}"
        }
        latest_messages = agent.messages[slice_idx :]
        _append_agent_message(agent, archive_message, team, manager)
        enriched_archive = agent.messages.pop()
        agent.messages = [first_msg, enriched_archive] + latest_messages

    _append_agent_message(
        agent, {"role": "user", "content": prompt}, team, manager
    )
    return identity_header

def parse_tool_args(args_str: str) -> Tuple[List[Any], Dict[str, Any]]:
    """Compatibility export for the strict literal argument parser."""
    return parse_tool_arguments(args_str)


def _extract_final_answer(text: str) -> Optional[str]:
    """Returns a line-delimited final answer without matching tool payloads."""
    if re.search(r"(?im)^\s*Action\s*:", text) or re.search(
        r"<action\s+name=", text, re.IGNORECASE
    ):
        return None
    matches = list(re.finditer(r"(?im)^\s*Final Answer\s*:\s*", text))
    if len(matches) != 1:
        return None
    return text[matches[0].end() :].strip()


def _turn_result(
    team: Any,
    agent: Agent,
    manager: Any,
    *,
    answer: Optional[str] = None,
    error_kind: Optional[str] = None,
    reason: Optional[str] = None,
    failures: Optional[List[ToolFailureSummary]] = None,
) -> AgentTurnResult:
    return AgentTurnResult(
        agent_id=agent.agent_id,
        team_id=team.team_id,
        turn_id=(manager._active_agent_turn_id.get() if manager else None),
        discussion_id=(
            manager._active_discussion_id.get() if manager else None
        ),
        round_number=(manager._active_round_number.get() if manager else None),
        status=(
            AgentTurnStatus.COMPLETED
            if error_kind is None
            else AgentTurnStatus.INCOMPLETE
        ),
        answer=answer,
        error_kind=error_kind,
        reason=reason,
        tool_failures=list(failures or []),
    )


def _available_tools(team: Any, agent: Agent, manager: Any) -> Dict[str, Any]:
    if manager and hasattr(manager, "get_available_tools"):
        return manager.get_available_tools(team, agent)
    return dict(getattr(team, "tools", {}) or {})


def _record_tool_result(
    manager: Any,
    team: Any,
    agent: Agent,
    result: ToolResult,
) -> None:
    """Emits privacy-safe invocation metadata for structured tool failures."""
    if manager is None or not result.failed:
        return
    payload = {
        "agent_id": agent.agent_id,
        "team_id": team.team_id,
        "discussion_id": manager._active_discussion_id.get(),
        "tool_name": result.name,
        "status": result.status.value,
        "error_kind": result.error_kind or result.status.value,
        "attempts": result.attempts,
    }
    manager.logger.info(
        "Tool invocation failed: agent=%s team=%s tool=%s status=%s attempts=%s",
        agent.agent_id,
        team.team_id,
        result.name,
        result.status.value,
        result.attempts,
    )
    manager._emit_callback("on_system_event", "tool_execution_failed", payload)
