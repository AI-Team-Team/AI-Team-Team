"""Agent inbox and consensual AgentTeam formation writes."""

from typing import Any, Dict, Iterable

from ai_team_team.database.models import (
    AgentInboxModel,
    TeamFormationDraftModel,
    TeamFormationInvitationModel,
    TeamFormationInvitationDecisionModel,
    TeamFormationRequestModel,
    TeamFormationRevisionModel,
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
                    content_fingerprint=request["content_fingerprint"],
                    revision_fingerprint=request["revision_fingerprint"],
                    status=request["status"],
                    created_team_id=request.get("created_team_id"),
                    decision_reason=request.get("decision_reason", ""),
                    created_at=request["created_at"],
                    updated_at=request["updated_at"],
                    resolved_at=request.get("resolved_at"),
                )
            )

    @staticmethod
    def _write_formation_revisions(session: Any, revisions: Iterable[Dict[str, Any]]) -> None:
        for revision in revisions:
            session.merge(
                TeamFormationRevisionModel(
                    revision_id=revision["revision_id"],
                    request_id=revision["request_id"],
                    proposal_revision=revision["proposal_revision"],
                    content_fingerprint=revision["content_fingerprint"],
                    revision_fingerprint=revision["revision_fingerprint"],
                    proposal_snapshot=revision["proposal_snapshot"],
                    revised_by_agent_id=revision["revised_by_agent_id"],
                    source_draft_id=revision.get("source_draft_id"),
                    created_at=revision["created_at"],
                )
            )

    @staticmethod
    def _write_formation_decisions(session: Any, decisions: Iterable[Dict[str, Any]]) -> None:
        for decision in decisions:
            session.merge(
                TeamFormationInvitationDecisionModel(
                    decision_id=decision["decision_id"],
                    request_id=decision["request_id"],
                    proposal_revision=decision["proposal_revision"],
                    agent_id=decision["agent_id"],
                    attitude=decision["attitude"],
                    created_at=decision["created_at"],
                )
            )

    @staticmethod
    def _write_formation_drafts(session: Any, drafts: Iterable[Dict[str, Any]]) -> None:
        for draft in drafts:
            session.merge(
                TeamFormationDraftModel(
                    draft_id=draft["draft_id"],
                    initiator_agent_id=draft["initiator_agent_id"],
                    creator_kind=draft["creator_kind"],
                    creator_agent_id=(
                        draft["creator_id"] if draft["creator_kind"] == "agent" else None
                    ),
                    creator_team_id=(
                        draft["creator_id"] if draft["creator_kind"] == "agent_team" else None
                    ),
                    deliberation_team_id=draft.get("creator_team_id"),
                    request_id=draft.get("request_id"),
                    base_revision=draft.get("base_revision"),
                    base_revision_fingerprint=draft.get("base_revision_fingerprint"),
                    objective=draft["objective"],
                    status=draft["status"],
                    participant_agent_ids=draft.get("participant_agent_ids", []),
                    source_discussion_id=draft.get("source_discussion_id"),
                    candidate=draft.get("candidate"),
                    reason=draft.get("reason", ""),
                    created_at=draft["created_at"],
                    updated_at=draft["updated_at"],
                )
            )

    @staticmethod
    def _write_formation_invitations(
        session: Any,
        invitations: Iterable[Dict[str, Any]],
        request_ids: Iterable[str],
    ) -> None:
        invitations = list(invitations)
        replaced_request_ids = set(request_ids)
        replaced_request_ids.update(
            invitation["request_id"] for invitation in invitations
        )
        for request_id in replaced_request_ids:
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
