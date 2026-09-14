"""Agent inbox and consensual AgentTeam formation writes."""

from typing import Any, Dict, Iterable

from ai_team_team.database.models import (
    AgentInboxModel,
    TeamFormationInvitationModel,
    TeamFormationRequestModel,
)


class FormationWriteMixin:
    @staticmethod
    def _write_agent_inboxes(session: Any, inboxes: Dict[str, Dict[str, Any]]) -> None:
        for agent_id, inbox in inboxes.items():
            session.query(AgentInboxModel).filter_by(agent_id=agent_id).delete(
                synchronize_session=False
            )
            for message in inbox["messages"]:
                session.add(
                    AgentInboxModel(
                        message_id=message["message_id"],
                        agent_id=agent_id,
                        message_type=message["message_type"],
                        payload=message.get("payload", {}),
                        created_at=message["created_at"],
                        read_at=message.get("read_at"),
                    )
                )

    @staticmethod
    def _write_formation_requests(session: Any, requests: Iterable[Dict[str, Any]]) -> None:
        for request in requests:
            session.merge(
                TeamFormationRequestModel(
                    request_id=request["request_id"],
                    initiator_agent_id=request["initiator_agent_id"],
                    creator_kind=request["creator_kind"],
                    creator_agent_id=(
                        request["creator_id"] if request["creator_kind"] == "agent" else None
                    ),
                    creator_team_id=(
                        request["creator_id"]
                        if request["creator_kind"] == "agent_team"
                        else None
                    ),
                    parent_team_id=request.get("parent_team_id"),
                    task=request.get("task"),
                    member_count=request["member_count"],
                    roles_and_presets=request.get("roles_and_presets"),
                    preset_name=request["preset_name"],
                    system_instructions=request["system_instructions"],
                    team_purpose=request["team_purpose"],
                    roles_and_models=request.get("roles_and_models"),
                    member_configs=request.get("member_configs"),
                    invitee_agent_ids=request["invitee_agent_ids"],
                    initial_docs=request.get("initial_docs"),
                    is_public_visible=int(request["is_public_visible"]),
                    initiator_joins=int(request["initiator_joins"]),
                    unanimous_acceptance_action=request["unanimous_acceptance_action"],
                    late_join_policy=request["late_join_policy"],
                    proposal_revision=request["proposal_revision"],
                    proposal_fingerprint=request["proposal_fingerprint"],
                    status=request["status"],
                    created_team_id=request.get("created_team_id"),
                    decision_reason=request.get("decision_reason", ""),
                    created_at=request["created_at"],
                    updated_at=request["updated_at"],
                    resolved_at=request.get("resolved_at"),
                )
            )

    @staticmethod
    def _write_formation_invitations(
        session: Any,
        invitations: Iterable[Dict[str, Any]],
    ) -> None:
        invitations = list(invitations)
        request_ids = {invitation["request_id"] for invitation in invitations}
        for request_id in request_ids:
            session.query(TeamFormationInvitationModel).filter_by(
                request_id=request_id
            ).delete(synchronize_session=False)
        for invitation in invitations:
            session.add(
                TeamFormationInvitationModel(
                    request_id=invitation["request_id"],
                    agent_id=invitation["agent_id"],
                    proposal_revision=invitation["proposal_revision"],
                    attitude=invitation["attitude"],
                    responded_at=invitation.get("responded_at"),
                    joined_at=invitation.get("joined_at"),
                    late_join_pending=int(invitation["late_join_pending"]),
                    late_join_requested_at=invitation.get("late_join_requested_at"),
                    late_join_decision=invitation.get("late_join_decision"),
                )
            )
