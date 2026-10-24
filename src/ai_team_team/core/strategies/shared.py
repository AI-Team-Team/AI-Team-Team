"""Privacy-safe context and result helpers for the personal runtime."""

import inspect
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_team_team.core.agent import Agent
from ai_team_team.core.response import (
    ToolResult,
)
from ai_team_team.core.text_action import parse_tool_arguments

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


def _is_private_call(name, arguments):
    return name in _PRIVATE_TOOL_NAMES or (name == "start_background_task"
        and isinstance(arguments, dict) and arguments.get("tool_name") in _PRIVATE_TOOL_NAMES)


def _compose_business_system_instruction(
    team_instruction: str,
    agent: Agent,
    identity_header: str,
    mode_instruction: str = "",
) -> str:
    """Composes the shared identity contract for every business-turn backend."""

    parts = []
    if team_instruction:
        parts.append(team_instruction)
    if agent.system_instructions:
        parts.append(
            "### YOUR INDIVIDUAL MISSION\n"
            f"{agent.system_instructions}"
        )
    if identity_header:
        parts.append(identity_header)
    if mode_instruction:
        parts.append(mode_instruction)
    return "\n\n".join(parts)


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
    """Records personal history with its invocation-scoped team provenance."""
    enriched = dict(message)
    enriched["team_id"] = getattr(team, "team_id", None)
    chain = manager._agent_invocation_chain.get() if manager else ()
    # The transitional call-chain token is not durable admission evidence.
    invocation_id = chain[-1][1] if chain else None
    activity = getattr(manager, "_activity", None) if manager else None
    active = activity.current.get() if activity is not None else None
    if active is not None and active.audit_profile is not None:
        agent.messages.append(dict(message))
        return
    if active is not None:
        invocation_id = active.invocation_id
    if manager and ("activity_invocations", (invocation_id,)) in manager._records.index:
        enriched["invocation_id"] = invocation_id
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
    actual["team_id"] = getattr(team, "team_id", None)
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
        arguments = function.get("arguments", {}) if isinstance(function, dict) else item.get("arguments", {})
        if _is_private_call(name, arguments):
            if isinstance(function, dict):
                safe_function = dict(function)
                safe_function["arguments"] = {"private_payload": "redacted"}
                item["function"] = safe_function
            if "arguments" in item:
                item["arguments"] = {"private_payload": "redacted"}
        sanitized.append(item)
    return sanitized


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


def _record_tool_result(
    manager: Any,
    team: Any,
    agent: Agent,
    result: ToolResult,
    *,
    known_tools=None,
) -> None:
    """Emits privacy-safe invocation metadata for structured tool failures."""
    if manager is None or not result.failed:
        return
    payload = {
        "agent_id": agent.agent_id,
        "team_id": getattr(team, "team_id", None),
        "tool_name": result.name if known_tools is None or result.name in known_tools else "<unregistered>",
        "status": result.status.value,
        "error_kind": result.error_kind or result.status.value,
        "attempts": result.attempts,
    }
    activity = getattr(manager, "_activity", None)
    session = activity.current.get() if activity is not None else None
    if session is not None:
        payload["invocation_id"] = session.invocation_id
    manager.logger.info(
        "Tool invocation failed: agent=%s team=%s tool=%s status=%s attempts=%s",
        agent.agent_id,
        getattr(team, "team_id", None),
        payload["tool_name"],
        result.status.value,
        result.attempts,
    )
    manager._emit_callback("on_system_event", "tool_execution_failed", payload)
