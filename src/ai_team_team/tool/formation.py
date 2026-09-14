"""Agent identity inbox and consensual team-formation tools."""

from typing import Any, Dict, List, Literal, Optional

from ..core.exceptions import ToolArgumentError, ToolBusinessError, ToolPermissionError
from .contract import Tool


def build_formation_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    def actor():
        current = att_manager._active_tool_agent.get() if att_manager is not None else None
        if current is None:
            raise ToolPermissionError("Team formation requires an active Agent invocation.")
        return current

    async def list_agent_inbox(unread_only: bool = True) -> str:
        """Lists notifications owned by the current Agent identity."""
        current = actor()
        messages = att_manager.list_agent_inbox(
            current.agent_id,
            unread_only=unread_only,
        )
        return "[" + ",".join(message.model_dump_json() for message in messages) + "]"

    async def mark_agent_inbox_read(message_ids: Optional[List[str]] = None) -> str:
        """Marks selected or all personal Agent inbox messages as read."""
        current = actor()
        changed = await att_manager.mark_agent_inbox_read(
            current.agent_id,
            message_ids,
        )
        return f'{{"status":"MARKED_READ","count":{changed}}}'

    async def inspect_team_formation(request_id: str) -> str:
        """Returns the four invitation-attitude counts and current creation eligibility."""
        try:
            return att_manager.inspect_team_formation(
                request_id,
                actor=actor(),
            ).model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def respond_team_invitation(
        request_id: str,
        attitude: Optional[
            Literal["accepted", "declined", "explicitly_ignored"]
        ] = None,
    ) -> str:
        """Publishes an attitude or deliberately withholds it by choosing None."""
        try:
            result = await att_manager.respond_team_invitation(
                request_id,
                actor=actor(),
                attitude=attitude,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def create_team_from_formation(request_id: str) -> str:
        """Creates an eligible AgentTeam from the currently accepted founding membership."""
        try:
            result = await att_manager.create_team_from_formation(
                request_id,
                actor=actor(),
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def abandon_team_formation(request_id: str, reason: str = "") -> str:
        """Abandons an uncreated proposal and notifies every invited Agent."""
        try:
            result = await att_manager.abandon_team_formation(
                request_id,
                actor=actor(),
                reason=reason,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def decide_team_formation_late_join(
        request_id: str,
        invitee_agent_id: str,
        approved: bool,
    ) -> str:
        """Lets the initiating Agent decide one pending late-join request."""
        try:
            result = await att_manager.decide_team_formation_late_join(
                request_id,
                invitee_agent_id,
                actor=actor(),
                approved=approved,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    return {
        "list_agent_inbox": Tool(
            "list_agent_inbox",
            "Lists persistent notifications belonging to the current Agent identity.",
            list_agent_inbox,
        ),
        "mark_agent_inbox_read": Tool(
            "mark_agent_inbox_read",
            "Marks selected personal inbox messages, or every message when omitted, as read.",
            mark_agent_inbox_read,
        ),
        "inspect_team_formation": Tool(
            "inspect_team_formation",
            "Shows accepted, declined, explicitly ignored, and no-response counts plus creation eligibility.",
            inspect_team_formation,
        ),
        "respond_team_invitation": Tool(
            "respond_team_invitation",
            "Choose accepted, declined, explicitly_ignored, or None. None deliberately withholds the Agent's public attitude and is externally indistinguishable from an unprocessed invitation; both appear as NO_RESPONSE.",
            respond_team_invitation,
        ),
        "create_team_from_formation": Tool(
            "create_team_from_formation",
            "Creates an eligible team from accepted invitees; only the initiating Agent may call it.",
            create_team_from_formation,
        ),
        "abandon_team_formation": Tool(
            "abandon_team_formation",
            "Abandons an uncreated formation and notifies every invitee.",
            abandon_team_formation,
        ),
        "decide_team_formation_late_join": Tool(
            "decide_team_formation_late_join",
            "Approves or denies a pending late join when the stored policy requires initiator confirmation.",
            decide_team_formation_late_join,
        ),
    }
