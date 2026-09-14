"""Strict validation for Agent inboxes and consensual team formation."""

from typing import Any, Dict, Iterable, Set

from ai_team_team.doc_library import DocumentLibrary

from ...exceptions import StateRestoreError
from ...formation import (
    AgentInboxMessage,
    InvitationAttitude,
    LateJoinPolicy,
    TeamFormationInvitation,
    TeamFormationRequest,
    TeamFormationStatus,
    UnanimousAcceptanceAction,
)


def validate_formations(
    manager: Any,
    payload: Any,
    agent_ids: Set[str],
    _active_agent_ids: Set[str],
    team_ids: Set[str],
) -> None:
    try:
        requests = [
            TeamFormationRequest.model_validate(row, strict=False)
            for row in payload.formation_requests
        ]
        invitations = [
            TeamFormationInvitation.model_validate(row, strict=False)
            for row in payload.formation_invitations
        ]
    except Exception as exc:
        raise StateRestoreError(f"Invalid persisted team formation record: {exc}") from exc
    request_ids = [request.request_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise StateRestoreError("Team formation request IDs are duplicated.")
    request_map = {request.request_id: request for request in requests}
    created_team_ids: set[str] = set()
    invitation_keys = [(item.request_id, item.agent_id) for item in invitations]
    if len(invitation_keys) != len(set(invitation_keys)):
        raise StateRestoreError("Team formation invitations are duplicated.")
    invitation_map: Dict[str, list[TeamFormationInvitation]] = {}
    for invitation in invitations:
        if invitation.request_id not in request_map:
            raise StateRestoreError(
                f"Formation invitation references missing request {invitation.request_id!r}."
            )
        if invitation.agent_id not in agent_ids:
            raise StateRestoreError(
                f"Formation invitation references missing Agent {invitation.agent_id!r}."
            )
        invitation_map.setdefault(invitation.request_id, []).append(invitation)

    team_rows = {row["team_id"]: row for row in payload.teams}
    for request in requests:
        if request.initiator_agent_id not in agent_ids:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has a missing initiator."
            )
        if len(request.invitee_agent_ids) != len(set(request.invitee_agent_ids)):
            raise StateRestoreError(f"Formation {request.request_id!r} has duplicate invitees.")
        if request.initiator_agent_id in request.invitee_agent_ids:
            raise StateRestoreError(
                f"Formation {request.request_id!r} invites its own initiator."
            )
        if set(request.invitee_agent_ids) - agent_ids:
            raise StateRestoreError(
                f"Formation {request.request_id!r} references missing invitees."
            )
        if request.creator_kind == "agent":
            if request.creator_id != request.initiator_agent_id or request.creator_id not in agent_ids:
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has an invalid Agent creator."
                )
        elif request.creator_id not in team_ids:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has a missing AgentTeam creator."
            )
        elif request.parent_team_id != request.creator_id:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has inconsistent AgentTeam creator provenance."
            )
        if request.parent_team_id is not None and request.parent_team_id not in team_ids:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has a missing intended parent."
            )
        actual_invitees = invitation_map.get(request.request_id, [])
        if {item.agent_id for item in actual_invitees} != set(request.invitee_agent_ids):
            raise StateRestoreError(
                f"Formation {request.request_id!r} does not have exactly one invitation per invitee."
            )
        if any(item.proposal_revision != request.proposal_revision for item in actual_invitees):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has stale invitation revisions."
            )
        fingerprint_payload = {
            "creator_kind": request.creator_kind,
            "creator_id": request.creator_id,
            "parent_team_id": request.parent_team_id,
            "task": request.task,
            "member_count": request.member_count,
            "roles_and_presets": request.roles_and_presets,
            "preset_name": request.preset_name,
            "system_instructions": request.system_instructions,
            "team_purpose": request.team_purpose,
            "roles_and_models": request.roles_and_models,
            "member_configs": request.member_configs,
            "invitee_agent_ids": request.invitee_agent_ids,
            "initial_docs": request.initial_docs,
            "is_public_visible": request.is_public_visible,
            "initiator_joins": request.initiator_joins,
            "unanimous_acceptance_action": request.unanimous_acceptance_action.value,
            "late_join_policy": request.late_join_policy.value,
            "proposal_revision": request.proposal_revision,
        }
        if manager._formations._proposal_fingerprint(fingerprint_payload) != request.proposal_fingerprint:
            raise StateRestoreError(
                f"Formation {request.request_id!r} failed proposal fingerprint validation."
            )
        _validate_request_configuration(manager, payload, request)
        potential_count = (
            (len(request.member_configs) if request.member_configs else 0)
            or (len(request.roles_and_presets) if request.roles_and_presets else 0)
        ) + len(request.invitee_agent_ids) + int(request.initiator_joins)
        if potential_count < payload.config.min_subagent_team_size:
            raise StateRestoreError(
                f"Formation {request.request_id!r} cannot satisfy the configured minimum size."
            )
        all_accepted = all(
            item.attitude is InvitationAttitude.ACCEPTED for item in actual_invitees
        )
        if request.status is TeamFormationStatus.READY_FOR_CONFIRMATION and (
            not all_accepted
            or request.unanimous_acceptance_action
            is not UnanimousAcceptanceAction.REQUIRE_CONFIRMATION
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an invalid confirmation-ready state."
            )
        if request.status is TeamFormationStatus.CREATED:
            if request.resolved_at is None:
                raise StateRestoreError(
                    f"Created formation {request.request_id!r} has no resolution timestamp."
                )
            team = team_rows.get(request.created_team_id or "")
            if team is None:
                raise StateRestoreError(
                    f"Created formation {request.request_id!r} references a missing AgentTeam."
                )
            if request.created_team_id in created_team_ids:
                raise StateRestoreError(
                    f"Created AgentTeam {request.created_team_id!r} belongs to multiple formations."
                )
            created_team_ids.add(request.created_team_id)
            expected_creator_type = (
                "agent" if request.creator_kind == "agent" else "team"
            )
            if (
                team.get("creator_type") != expected_creator_type
                or team.get("creator_id") != request.creator_id
            ):
                raise StateRestoreError(
                    f"Created formation {request.request_id!r} has inconsistent creator provenance."
                )
            for invitation in actual_invitees:
                if invitation.joined_at is not None and invitation.attitude is not InvitationAttitude.ACCEPTED:
                    raise StateRestoreError(
                        f"Formation {request.request_id!r} joined an Agent without acceptance."
                    )
                if invitation.late_join_pending and (
                    request.late_join_policy
                    is not LateJoinPolicy.REQUIRE_INITIATOR_CONFIRMATION
                    or invitation.attitude is not InvitationAttitude.ACCEPTED
                ):
                    raise StateRestoreError(
                        f"Formation {request.request_id!r} has an invalid pending late join."
                    )
        elif request.status is TeamFormationStatus.ABANDONED:
            if request.resolved_at is None or request.created_team_id is not None:
                raise StateRestoreError(
                    f"Abandoned formation {request.request_id!r} has invalid terminal state."
                )
            if any(item.joined_at is not None or item.late_join_pending for item in actual_invitees):
                raise StateRestoreError(
                    f"Abandoned formation {request.request_id!r} contains membership state."
                )
        elif request.created_team_id is not None or any(
            item.joined_at is not None or item.late_join_pending for item in actual_invitees
        ):
            raise StateRestoreError(
                f"Uncreated formation {request.request_id!r} contains created membership state."
            )
        elif request.resolved_at is not None:
            raise StateRestoreError(
                f"Open formation {request.request_id!r} has a resolution timestamp."
            )

        for invitation in actual_invitees:
            if (
                invitation.attitude is InvitationAttitude.NO_RESPONSE
            ) != (invitation.responded_at is None):
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has inconsistent response timestamps."
                )
            if invitation.late_join_pending and (
                invitation.late_join_requested_at is None
                or invitation.late_join_decision is not None
            ):
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has inconsistent late-join state."
                )
            if invitation.late_join_decision == "denied" and (
                invitation.late_join_requested_at is None
                or invitation.joined_at is not None
            ):
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has an invalid denied late join."
                )
            if invitation.late_join_decision == "approved" and invitation.joined_at is None:
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has an invalid approved late join."
                )
            if (
                invitation.late_join_requested_at is not None
                and not invitation.late_join_pending
                and invitation.late_join_decision != "denied"
            ):
                raise StateRestoreError(
                    f"Formation {request.request_id!r} retains an invalid late-join request."
                )

    _validate_agent_inboxes(payload.agent_inboxes, agent_ids)


def _validate_request_configuration(
    manager: Any,
    payload: Any,
    request: TeamFormationRequest,
) -> None:
    if request.member_configs is not None and request.roles_and_presets is not None:
        raise StateRestoreError(
            f"Formation {request.request_id!r} has conflicting new-Agent specifications."
        )
    available_aliases = set(manager.llm_clients) | set(payload.model_configs) | {"default"}
    for role, config in (request.member_configs or {}).items():
        if not isinstance(role, str) or not role:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an invalid member role."
            )
        unknown = set(config) - {"model", "role_description", "system_instructions"}
        if unknown:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has unknown member fields: {sorted(unknown)}."
            )
        alias = config.get("model")
        if alias is not None and (
            not isinstance(alias, str) or not alias or alias not in available_aliases
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an unavailable model alias."
            )
        for field in ("role_description", "system_instructions"):
            if field in config and not isinstance(config[field], str):
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has an invalid {field}."
                )
    for item in request.roles_and_presets or []:
        if len(item) != 2 or not all(isinstance(value, str) and value for value in item):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has invalid role and preset data."
            )
    for role, alias in (request.roles_and_models or {}).items():
        if (
            not isinstance(role, str)
            or not role
            or not isinstance(alias, str)
            or not alias
            or alias not in available_aliases
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has unavailable role model data."
            )
    for path, content in (request.initial_docs or {}).items():
        if not isinstance(path, str) or not isinstance(content, str):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has invalid initial documents."
            )
        try:
            DocumentLibrary._normalize_path(path, allow_root=False)
        except (PermissionError, ValueError) as exc:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an unsafe initial document path."
            ) from exc


def _validate_agent_inboxes(
    inboxes: Dict[str, Iterable[Dict[str, Any]]],
    agent_ids: Set[str],
) -> None:
    message_ids = set()
    for agent_id, rows in inboxes.items():
        if agent_id not in agent_ids:
            raise StateRestoreError(f"Agent inbox references missing Agent {agent_id!r}.")
        for row in rows:
            try:
                message = AgentInboxMessage.model_validate(row, strict=False)
            except Exception as exc:
                raise StateRestoreError(f"Invalid Agent inbox message: {exc}") from exc
            if message.agent_id != agent_id:
                raise StateRestoreError(
                    f"Agent inbox message {message.message_id!r} has the wrong owner."
                )
            if message.message_id in message_ids:
                raise StateRestoreError("Agent inbox message IDs are duplicated.")
            message_ids.add(message.message_id)
