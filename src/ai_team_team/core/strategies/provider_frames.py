"""Recovery of interrupted provider frames; no independent inference loop."""

from typing import Any

from ai_team_team.core.agent import Agent
from .shared import _append_agent_message

def _close_interrupted_tool_batch(team: Any, agent: Agent, manager: Any) -> None:
    """Closes an interrupted provider exchange without guessing tool side effects."""
    pending = {}
    for message in agent.messages:
        if message.get("tool_calls"):
            pending = {
                call["id"]: call["function"]["name"] for call in message["tool_calls"]
            }
        elif message.get("role") == "tool":
            pending.pop(message.get("tool_call_id"), None)
    for call_id, name in pending.items():
        message = {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": (
                    "[interrupted] The invocation ended before its response was recorded. "
                    "Its effects may already have committed; inspect authoritative state "
                    "before deciding whether to retry."
                ),
            }
        activity = getattr(manager, "_activity", None)
        session = activity.current.get() if activity is not None else None
        if session is not None and session.agent_id == agent.agent_id and session.audit_profile is not None:
            activity.append(session, message)
        else:
            _append_agent_message(agent, message, team, manager)
