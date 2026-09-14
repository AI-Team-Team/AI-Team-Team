"""Agent identity inbox and consensual team-formation tools."""

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from ..core.exceptions import ToolArgumentError, ToolBusinessError, ToolPermissionError
from ..core.formation import TeamFormationRevisionPatch
from .contract import Tool


PositiveRevision = Annotated[int, Field(ge=1)]


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
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def discuss_team_formation_proposal(
        objective: str,
        request_id: Optional[str] = None,
    ) -> str:
        """Schedules creator-team deliberation for an initial or revised proposal."""
        try:
            if request_id is None:
                if not att_manager.config.enable_dynamic_delegation:
                    raise ToolPermissionError("Dynamic Subagent Delegation is disabled.")
                current_team = att_manager._active_team.get()
                if (
                    current_team is not None
                    and current_team.depth >= att_manager.config.max_delegation_depth
                ):
                    raise ToolBusinessError(
                        f"Max delegation depth ({att_manager.config.max_delegation_depth}) "
                        "reached; cannot design a child AgentTeam."
                    )
            draft = await att_manager.discuss_team_formation_proposal(
                actor=actor(),
                objective=objective,
                request_id=request_id,
            )
            return draft.model_dump_json()
        except (ToolPermissionError, ToolBusinessError):
            raise
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def inspect_team_formation_draft(draft_id: str) -> str:
        """Returns the current state and candidate for the caller's own draft."""
        try:
            return att_manager.get_team_formation_draft(
                draft_id,
                actor=actor(),
            ).model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def retry_team_formation_draft(draft_id: str) -> str:
        """Retries a pending, failed, or cancelled detached deliberation job."""
        try:
            draft = await att_manager.retry_team_formation_draft(
                draft_id,
                actor=actor(),
            )
            return draft.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def publish_team_formation_draft(draft_id: str) -> str:
        """Explicitly publishes the caller's ready structured proposal draft."""
        try:
            result = await att_manager.publish_team_formation_draft(
                draft_id,
                actor=actor(),
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def respond_team_invitation(
        request_id: str,
        proposal_revision: PositiveRevision,
        attitude: Optional[
            Literal["accepted", "declined", "explicitly_ignored"]
        ] = None,
    ) -> str:
        """Publishes an attitude or deliberately withholds it by choosing None."""
        try:
            result = await att_manager.respond_team_invitation(
                request_id,
                actor=actor(),
                proposal_revision=proposal_revision,
                attitude=attitude,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def create_team_from_formation(
        request_id: str,
        proposal_revision: PositiveRevision,
    ) -> str:
        """Creates an eligible AgentTeam from the currently accepted founding membership."""
        try:
            result = await att_manager.create_team_from_formation(
                request_id,
                actor=actor(),
                proposal_revision=proposal_revision,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def revise_team_formation(
        request_id: str,
        base_revision: PositiveRevision,
        changes: TeamFormationRevisionPatch,
    ) -> str:
        """Publishes a validated material revision and resets retained consent."""
        try:
            result = await att_manager.revise_team_formation(
                request_id,
                actor=actor(),
                base_revision=base_revision,
                changes=changes,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def abandon_team_formation(
        request_id: str,
        proposal_revision: PositiveRevision,
        reason: str = "",
    ) -> str:
        """Abandons an uncreated proposal and notifies every invited Agent."""
        try:
            result = await att_manager.abandon_team_formation(
                request_id,
                actor=actor(),
                proposal_revision=proposal_revision,
                reason=reason,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolBusinessError(str(exc)) from exc

    async def decide_team_formation_late_join(
        request_id: str,
        invitee_agent_id: str,
        proposal_revision: PositiveRevision,
        approved: bool,
    ) -> str:
        """Lets the initiating Agent decide one pending late-join request."""
        try:
            result = await att_manager.decide_team_formation_late_join(
                request_id,
                invitee_agent_id,
                actor=actor(),
                proposal_revision=proposal_revision,
                approved=approved,
            )
            return result.model_dump_json()
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
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
        "discuss_team_formation_proposal": Tool(
            "discuss_team_formation_proposal",
            "Schedules a detached advisory discussion in the current creator AgentTeam. The returned draft must later be inspected and explicitly published; it never grants invitee consent.",
            discuss_team_formation_proposal,
        ),
        "inspect_team_formation_draft": Tool(
            "inspect_team_formation_draft",
            "Inspects the current Agent's own detached formation draft and its validated candidate when ready.",
            inspect_team_formation_draft,
        ),
        "retry_team_formation_draft": Tool(
            "retry_team_formation_draft",
            "Explicitly retries a pending, failed, or cancelled formation-draft job.",
            retry_team_formation_draft,
        ),
        "publish_team_formation_draft": Tool(
            "publish_team_formation_draft",
            "Publishes a ready structured draft as revision 1 or as the next exact proposal revision. Publication never accepts an invitation for another Agent.",
            publish_team_formation_draft,
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
        "revise_team_formation": Tool(
            "revise_team_formation",
            "Revises an open proposal from an explicitly reviewed base revision; every retained invitee must consent again.",
            revise_team_formation,
            prompt_schema_mode="full",
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
