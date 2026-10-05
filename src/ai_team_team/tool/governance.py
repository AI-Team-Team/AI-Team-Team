"""Voluntary personal email inspection and explicitly submitted public choices."""

import json
from typing import Any, Dict, Union

from ..core.exceptions import ToolArgumentError, ToolPermissionError
from ..core.governance import BooleanGovernanceChoice, ModelGovernanceChoice
from .contract import Tool


def build_governance_tools(manager: Any) -> Dict[str, Tool]:
    def actor():
        current = manager._active_tool_agent.get() if manager is not None else None
        if (
            current is None
            or manager._agents_by_id.get(current.agent_id) is not current
            or current.lifecycle_state != "active"
        ):
            raise ToolPermissionError(
                "Personal governance tools require the addressed active Agent."
            )
        return current

    async def open_agent_mail(message_id: str) -> dict:
        """Opens your own email without marking it read or casting any choice."""
        try:
            return manager.open_agent_mail(message_id, actor=actor())
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolArgumentError("The personal email reference is invalid.") from exc

    async def submit_governance_choice(
        round_id: str, choice: Union[BooleanGovernanceChoice, ModelGovernanceChoice]
    ):
        """Explicitly submits your immutable choice for one round, independently of email read state."""
        try:
            return await manager.submit_governance_choice(
                round_id, choice.model_dump(mode="json"), actor=actor()
            )
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc

    async def list_governance_requests(pending_only: bool = True) -> str:
        """Lists your own governance rounds, including unanswered requests whose emails are already read."""
        return json.dumps(
            manager.list_governance_requests(actor=actor(), pending_only=pending_only),
            sort_keys=True,
        )

    return {
        "open_agent_mail": Tool(
            "open_agent_mail", open_agent_mail.__doc__, open_agent_mail, memory_capture="content"
        ),
        "submit_governance_choice": Tool(
            "submit_governance_choice",
            submit_governance_choice.__doc__,
            submit_governance_choice,
            memory_capture="content",
        ),
        "list_governance_requests": Tool(
            "list_governance_requests",
            list_governance_requests.__doc__,
            list_governance_requests,
            memory_capture="content",
        ),
    }
