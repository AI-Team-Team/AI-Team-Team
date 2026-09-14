"""Strict validation for Agent inboxes and consensual team formation."""

from typing import Any, Dict, Iterable, Set

from ai_team_team.doc_library import DocumentLibrary

from ...exceptions import StateRestoreError
from ...formation import (
    AgentInboxMessage,
    FormationDraftStatus,
    InvitationAttitude,
    LateJoinPolicy,
    TeamFormationDraft,
    TeamFormationDraftCandidate,
    TeamFormationInvitation,
    TeamFormationInvitationDecision,
    TeamFormationRequest,
    TeamFormationRevision,
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
        revisions = [
            TeamFormationRevision.model_validate(row, strict=False)
            for row in payload.formation_revisions
        ]
        decisions = [
            TeamFormationInvitationDecision.model_validate(row, strict=False)
            for row in payload.formation_decisions
        ]
        drafts = [
            TeamFormationDraft.model_validate(row, strict=False)
            for row in payload.formation_drafts
        ]
    except Exception as exc:
        raise StateRestoreError(f"Invalid persisted team formation record: {exc}") from exc
    request_ids = [request.request_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise StateRestoreError("Team formation request IDs are duplicated.")
    request_map = {request.request_id: request for request in requests}
    revision_ids = [item.revision_id for item in revisions]
    if len(revision_ids) != len(set(revision_ids)):
        raise StateRestoreError("Team formation revision IDs are duplicated.")
    revision_keys = [
        (item.request_id, item.proposal_revision) for item in revisions
    ]
    if len(revision_keys) != len(set(revision_keys)):
        raise StateRestoreError("Team formation revision numbers are duplicated.")
    revision_map = {
        (item.request_id, item.proposal_revision): item for item in revisions
    }
    decision_ids = [item.decision_id for item in decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise StateRestoreError("Team formation decision IDs are duplicated.")
    draft_ids = [item.draft_id for item in drafts]
    if len(draft_ids) != len(set(draft_ids)):
        raise StateRestoreError("Team formation draft IDs are duplicated.")
    draft_map = {item.draft_id: item for item in drafts}
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
        if not request.invitee_agent_ids and not request.initiator_joins:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has no existing founding Agent."
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
        content_payload = manager._formations._request_content(request)
        content_fingerprint = manager._formations._proposal_fingerprint(
            content_payload
        )
        if content_fingerprint != request.content_fingerprint:
            raise StateRestoreError(
                f"Formation {request.request_id!r} failed content fingerprint validation."
            )
        revision_fingerprint = manager._formations._revision_fingerprint(
            request.request_id,
            request.proposal_revision,
            content_fingerprint,
        )
        if revision_fingerprint != request.revision_fingerprint:
            raise StateRestoreError(
                f"Formation {request.request_id!r} failed revision fingerprint validation."
            )
        request_revisions = sorted(
            (
                item
                for item in revisions
                if item.request_id == request.request_id
            ),
            key=lambda item: item.proposal_revision,
        )
        if [item.proposal_revision for item in request_revisions] != list(
            range(1, request.proposal_revision + 1)
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has incomplete revision history."
            )
        if any(
            previous.content_fingerprint == current.content_fingerprint
            for previous, current in zip(request_revisions, request_revisions[1:])
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} contains a persisted no-op revision."
            )
        current_revision = revision_map.get(
            (request.request_id, request.proposal_revision)
        )
        if (
            current_revision is None
            or current_revision.content_fingerprint != content_fingerprint
            or current_revision.revision_fingerprint != revision_fingerprint
            or current_revision.proposal_snapshot != content_payload
        ):
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an inconsistent current revision snapshot."
            )
        _validate_request_configuration(manager, payload, request)
        all_accepted = all(
            item.attitude is InvitationAttitude.ACCEPTED for item in actual_invitees
        )
        if request.status in {
            TeamFormationStatus.COLLECTING_RESPONSES,
            TeamFormationStatus.READY_FOR_CONFIRMATION,
        }:
            should_be_ready = (
                all_accepted
                and request.unanimous_acceptance_action
                is UnanimousAcceptanceAction.REQUIRE_CONFIRMATION
            )
            if (
                request.status is TeamFormationStatus.READY_FOR_CONFIRMATION
            ) is not should_be_ready:
                raise StateRestoreError(
                    f"Formation {request.request_id!r} has an inconsistent open status."
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

    for revision in revisions:
        request = request_map.get(revision.request_id)
        if request is None:
            raise StateRestoreError("A formation revision references a missing request.")
        if revision.revision_id != f"{revision.request_id}:{revision.proposal_revision}":
            raise StateRestoreError("A formation revision has an invalid stable identifier.")
        if revision.revised_by_agent_id != request.initiator_agent_id:
            raise StateRestoreError(
                "A formation revision was not committed by the immutable initiating Agent."
            )
        historical = _validate_revision_snapshot(
            manager,
            payload,
            request,
            revision,
            agent_ids,
            team_ids,
        )
        expected_content = manager._formations._proposal_fingerprint(
            manager._formations._request_content(historical)
        )
        expected_revision = manager._formations._revision_fingerprint(
            revision.request_id,
            revision.proposal_revision,
            expected_content,
        )
        if (
            expected_content != revision.content_fingerprint
            or expected_revision != revision.revision_fingerprint
        ):
            raise StateRestoreError("A formation revision snapshot failed fingerprint validation.")
        if revision.source_draft_id is not None:
            draft = draft_map.get(revision.source_draft_id)
            if draft is None or draft.status is not FormationDraftStatus.PUBLISHED:
                raise StateRestoreError("A formation revision references an invalid source draft.")

    for request in requests:
        request_revisions = sorted(
            (
                revision
                for revision in revisions
                if revision.request_id == request.request_id
            ),
            key=lambda revision: revision.proposal_revision,
        )
        if request_revisions[0].created_at != request.created_at:
            raise StateRestoreError(
                f"Formation {request.request_id!r} has an invalid initial revision timestamp."
            )

    for decision in decisions:
        revision = revision_map.get(
            (decision.request_id, decision.proposal_revision)
        )
        if revision is None or decision.agent_id not in agent_ids:
            raise StateRestoreError("A formation decision has a missing reference.")
        if decision.agent_id not in revision.proposal_snapshot.get(
            "invitee_agent_ids", []
        ):
            raise StateRestoreError(
                "A formation decision was recorded for an Agent outside that revision."
            )

    decisions_by_invitation: Dict[
        tuple[str, int, str], list[TeamFormationInvitationDecision]
    ] = {}
    for decision in decisions:
        decisions_by_invitation.setdefault(
            (decision.request_id, decision.proposal_revision, decision.agent_id),
            [],
        ).append(decision)
    for request in requests:
        for invitation in invitation_map.get(request.request_id, []):
            current_decisions = decisions_by_invitation.get(
                (
                    request.request_id,
                    request.proposal_revision,
                    invitation.agent_id,
                ),
                [],
            )
            if not current_decisions:
                if invitation.attitude is not InvitationAttitude.NO_RESPONSE:
                    raise StateRestoreError(
                        "A current formation invitation attitude has no decision history."
                    )
                continue
            matching_times = [
                decision.created_at
                for decision in current_decisions
                if decision.attitude is invitation.attitude
            ]
            if not matching_times:
                raise StateRestoreError(
                    "A current formation invitation conflicts with its decision history."
                )
            latest_matching_time = max(matching_times)
            if any(
                decision.attitude is not invitation.attitude
                and decision.created_at > latest_matching_time
                for decision in current_decisions
            ):
                raise StateRestoreError(
                    "A current formation invitation is older than its decision history."
                )

    _validate_drafts(
        manager,
        payload,
        drafts,
        request_map,
        revision_map,
        agent_ids,
        team_ids,
    )
    _validate_agent_inboxes(payload.agent_inboxes, agent_ids)


def _validate_revision_snapshot(
    manager: Any,
    payload: Any,
    current: TeamFormationRequest,
    revision: TeamFormationRevision,
    agent_ids: Set[str],
    team_ids: Set[str],
) -> TeamFormationRequest:
    """Validates one historical snapshot as a complete normalized proposal."""
    expected_keys = set(manager._formations._request_content(current))
    if type(revision.proposal_snapshot) is not dict or set(revision.proposal_snapshot) != expected_keys:
        raise StateRestoreError(
            "A formation revision snapshot does not contain the exact material field set."
        )
    restored = current.model_dump(mode="python")
    restored.update(revision.proposal_snapshot)
    restored.update(
        {
            "proposal_revision": revision.proposal_revision,
            "content_fingerprint": revision.content_fingerprint,
            "revision_fingerprint": revision.revision_fingerprint,
            "status": TeamFormationStatus.COLLECTING_RESPONSES,
            "created_team_id": None,
            "decision_reason": "",
            "updated_at": revision.created_at,
            "resolved_at": None,
        }
    )
    try:
        historical = TeamFormationRequest.model_validate(restored, strict=False)
    except Exception as exc:
        raise StateRestoreError(
            f"A formation revision contains an invalid proposal snapshot: {exc}"
        ) from exc
    if (
        historical.initiator_agent_id != current.initiator_agent_id
        or historical.creator_kind != current.creator_kind
        or historical.creator_id != current.creator_id
        or historical.parent_team_id != current.parent_team_id
    ):
        raise StateRestoreError(
            "A formation revision changed immutable creator or initiator provenance."
        )
    if len(historical.invitee_agent_ids) != len(set(historical.invitee_agent_ids)):
        raise StateRestoreError("A formation revision contains duplicate invitees.")
    if historical.initiator_agent_id in historical.invitee_agent_ids:
        raise StateRestoreError("A formation revision invites its own initiating Agent.")
    if not historical.invitee_agent_ids and not historical.initiator_joins:
        raise StateRestoreError(
            "A formation revision has no existing founding Agent."
        )
    if set(historical.invitee_agent_ids) - agent_ids:
        raise StateRestoreError("A formation revision references missing invitees.")
    if historical.creator_kind == "agent":
        if historical.creator_id not in agent_ids:
            raise StateRestoreError("A formation revision references a missing Agent creator.")
    elif historical.creator_id not in team_ids:
        raise StateRestoreError("A formation revision references a missing AgentTeam creator.")
    _validate_request_configuration(manager, payload, historical)
    return historical


def _validate_drafts(
    manager: Any,
    payload: Any,
    drafts: Iterable[TeamFormationDraft],
    request_map: Dict[str, TeamFormationRequest],
    revision_map: Dict[tuple[str, int], TeamFormationRevision],
    agent_ids: Set[str],
    team_ids: Set[str],
) -> None:
    revisions_by_source_draft: Dict[str, list[TeamFormationRevision]] = {}
    for revision in revision_map.values():
        if revision.source_draft_id is not None:
            revisions_by_source_draft.setdefault(
                revision.source_draft_id,
                [],
            ).append(revision)
    for draft in drafts:
        if draft.initiator_agent_id not in agent_ids:
            raise StateRestoreError("A formation draft references a missing initiator.")
        if draft.creator_kind == "agent":
            if (
                draft.creator_id != draft.initiator_agent_id
                or draft.creator_team_id is not None
            ):
                raise StateRestoreError("A formation draft has invalid Agent provenance.")
        elif (
            draft.creator_id not in team_ids
            or draft.creator_team_id != draft.creator_id
        ):
            raise StateRestoreError(
                "A formation draft has invalid creator AgentTeam provenance."
            )
        if set(draft.participant_agent_ids) - agent_ids:
            raise StateRestoreError("A formation draft references missing participants.")
        if len(draft.participant_agent_ids) != len(set(draft.participant_agent_ids)):
            raise StateRestoreError("A formation draft contains duplicate participants.")
        if draft.request_id is None:
            if draft.base_revision is not None or draft.base_revision_fingerprint is not None:
                raise StateRestoreError("An initial formation draft has revision state.")
        else:
            request = request_map.get(draft.request_id)
            if request is None or draft.base_revision is None:
                raise StateRestoreError("A revision draft references a missing request revision.")
            if request.initiator_agent_id != draft.initiator_agent_id:
                raise StateRestoreError("A revision draft has a different initiating Agent.")
            if request.parent_team_id is None:
                if draft.creator_kind != "agent":
                    raise StateRestoreError(
                        "A standalone revision draft has invalid creator provenance."
                    )
            elif (
                draft.creator_kind != "agent_team"
                or draft.creator_id != request.parent_team_id
            ):
                raise StateRestoreError(
                    "A revision draft does not use the immutable creator AgentTeam."
                )
            revision = revision_map.get((draft.request_id, draft.base_revision))
            if (
                revision is None
                or revision.revision_fingerprint != draft.base_revision_fingerprint
            ):
                raise StateRestoreError("A revision draft has an invalid base fingerprint.")
        if draft.status in {
            FormationDraftStatus.READY,
            FormationDraftStatus.PUBLISHED,
        } and draft.candidate is None:
            raise StateRestoreError("A publishable formation draft has no candidate.")
        if draft.status in {
            FormationDraftStatus.PENDING,
            FormationDraftStatus.RUNNING,
            FormationDraftStatus.FAILED,
            FormationDraftStatus.CANCELLED,
        } and draft.candidate is not None:
            raise StateRestoreError(
                "An unfinished formation draft unexpectedly contains a candidate."
            )
        if draft.creator_team_id is not None and (
            draft.status in {
                FormationDraftStatus.READY,
                FormationDraftStatus.PUBLISHED,
            }
            or (
                draft.status is FormationDraftStatus.STALE
                and draft.candidate is not None
            )
        ):
            if not draft.source_discussion_id or not draft.participant_agent_ids:
                raise StateRestoreError("A team-deliberated draft lacks discussion provenance.")
        if draft.candidate is not None:
            candidate = draft.candidate
            if len(candidate.existing_member_ids) != len(
                set(candidate.existing_member_ids)
            ):
                raise StateRestoreError(
                    "A formation draft candidate contains duplicate invitees."
                )
            if draft.initiator_agent_id in candidate.existing_member_ids:
                raise StateRestoreError(
                    "A formation draft candidate invites its own initiator."
                )
            if set(candidate.existing_member_ids) - agent_ids:
                raise StateRestoreError(
                    "A formation draft candidate references missing invitees."
                )
            if not candidate.existing_member_ids and not candidate.initiator_joins:
                raise StateRestoreError(
                    "A formation draft candidate has no existing founding Agent."
                )
            _validate_draft_candidate_configuration(
                manager,
                payload,
                candidate,
            )
            if draft.request_id is not None and draft.status is FormationDraftStatus.READY:
                current = request_map[draft.request_id]
                if (
                    current.status
                    not in {
                        TeamFormationStatus.COLLECTING_RESPONSES,
                        TeamFormationStatus.READY_FOR_CONFIRMATION,
                    }
                    or current.proposal_revision != draft.base_revision
                    or current.revision_fingerprint != draft.base_revision_fingerprint
                ):
                    raise StateRestoreError(
                        "A ready formation draft is detached from its current base revision."
                    )
        source_revisions = revisions_by_source_draft.get(draft.draft_id, [])
        if len(source_revisions) > 1:
            raise StateRestoreError(
                "A formation draft is the source of multiple immutable revisions."
            )
        if source_revisions:
            source = source_revisions[0]
            source_request = request_map[source.request_id]
            if draft.status is not FormationDraftStatus.PUBLISHED:
                raise StateRestoreError(
                    "A non-published draft is referenced by an immutable revision."
                )
            if source_request.initiator_agent_id != draft.initiator_agent_id:
                raise StateRestoreError(
                    "A published draft and its formation have different initiators."
                )
            if (
                source.proposal_snapshot["creator_kind"] != draft.creator_kind
                or source.proposal_snapshot["creator_id"] != draft.creator_id
                or source.proposal_snapshot["parent_team_id"] != draft.creator_team_id
            ):
                raise StateRestoreError(
                    "A published draft has inconsistent creator provenance."
                )
            if _candidate_material_content(draft.candidate) != {
                key: value
                for key, value in source.proposal_snapshot.items()
                if key not in {"creator_kind", "creator_id", "parent_team_id"}
            }:
                raise StateRestoreError(
                    "A published draft candidate does not match its immutable revision."
                )
            if draft.request_id is None:
                if source.proposal_revision != 1:
                    raise StateRestoreError(
                        "An initial formation draft did not publish revision 1."
                    )
            elif (
                source.request_id != draft.request_id
                or source.proposal_revision != draft.base_revision + 1
            ):
                raise StateRestoreError(
                    "A revision draft published an inconsistent successor revision."
                )
        elif (
            draft.status is FormationDraftStatus.PUBLISHED
            and draft.request_id is not None
        ):
            base = revision_map.get((draft.request_id, draft.base_revision or 0))
            if base is None or _candidate_material_content(draft.candidate) != {
                key: value
                for key, value in base.proposal_snapshot.items()
                if key not in {"creator_kind", "creator_id", "parent_team_id"}
            }:
                raise StateRestoreError(
                    "A published revision draft without a successor is not a valid no-op."
                )
        elif (
            draft.status is FormationDraftStatus.PUBLISHED
            and draft.request_id is None
        ):
            raise StateRestoreError(
                "A published initial draft has no resulting immutable revision."
            )


def _candidate_material_content(
    candidate: TeamFormationDraftCandidate | None,
) -> Dict[str, Any]:
    if candidate is None:
        return {}
    content = candidate.model_dump(mode="json")
    content["invitee_agent_ids"] = content.pop("existing_member_ids")
    return content


def _validate_draft_candidate_configuration(
    manager: Any,
    payload: Any,
    candidate: Any,
) -> None:
    request = TeamFormationRequest(
        request_id="__draft_validation__",
        initiator_agent_id="__draft_validation__",
        creator_kind="agent",
        creator_id="__draft_validation__",
        task=candidate.task,
        member_count=candidate.member_count,
        roles_and_presets=candidate.roles_and_presets,
        preset_name=candidate.preset_name,
        system_instructions=candidate.system_instructions,
        team_purpose=candidate.team_purpose,
        roles_and_models=candidate.roles_and_models,
        member_configs=candidate.member_configs,
        invitee_agent_ids=candidate.existing_member_ids,
        initial_docs=candidate.initial_docs,
        is_public_visible=candidate.is_public_visible,
        initiator_joins=candidate.initiator_joins,
        unanimous_acceptance_action=candidate.unanimous_acceptance_action,
        late_join_policy=candidate.late_join_policy,
        content_fingerprint="validation",
        revision_fingerprint="validation",
        created_at=0.0,
        updated_at=0.0,
    )
    _validate_request_configuration(manager, payload, request)


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
