"""Transactional full and incremental ATT state writes."""

import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import delete, text

from ai_team_team.database.models import (
    AgentMessageModel,
    AgentModel,
    CommunicationAgreementModel,
    CommunicationApprovalModel,
    CommunicationBallotModel,
    CommunicationRequestModel,
    DocLibFileModel,
    DocLibLinkModel,
    LibraryModel,
    LibraryPermissionModel,
    ManagerConfigModel,
    PeerMessageModel,
    TeamInboxModel,
    TeamModel,
    TeamProposalModel,
    team_members,
)


class StoreWriteMixin:
    session_factory: Any
    _materialize: Callable[[Dict[str, Any]], Dict[str, Any]]

    def write(self, snapshot: Dict[str, Any]) -> None:
        """Writes a full snapshot or an incremental immutable delta."""
        snapshot = self._materialize(snapshot)
        session = self.session_factory()
        try:
            if snapshot["full"]:
                session.execute(text("PRAGMA defer_foreign_keys = ON"))
                self._clear_all(session)

            self._write_deletions(session, snapshot)

            self._write_configs(session, snapshot.get("configs"))
            self._write_agents(session, snapshot.get("agents", []))
            session.flush()
            self._write_teams(session, snapshot.get("teams", []))
            session.flush()
            self._write_inboxes(session, snapshot.get("inboxes", {}))
            self._write_proposals(session, snapshot.get("proposals", {}))
            self._write_communication_requests(session, snapshot.get("communication_requests", []))
            session.flush()
            self._write_communication_approvals(
                session,
                snapshot.get("communication_approvals", []),
                snapshot.get("communication_ballots", []),
            )
            self._write_communication_agreements(
                session, snapshot.get("communication_agreements", [])
            )
            self._write_peer_messages(session, snapshot.get("peer_messages", []))
            self._write_libraries(session, snapshot.get("libraries", []))
            session.flush()
            self._write_permissions(session, snapshot.get("permissions", {}))
            self._write_file_changes(session, snapshot.get("file_changes", {}))
            self._write_links(session, snapshot.get("links"))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _clear_all(session: Any) -> None:
        for model in (
            AgentMessageModel,
            TeamInboxModel,
            TeamProposalModel,
            PeerMessageModel,
            CommunicationBallotModel,
            CommunicationAgreementModel,
            CommunicationApprovalModel,
            CommunicationRequestModel,
            LibraryPermissionModel,
            DocLibFileModel,
            DocLibLinkModel,
        ):
            session.query(model).delete(synchronize_session=False)
        session.execute(delete(team_members))
        session.query(LibraryModel).delete(synchronize_session=False)
        session.query(TeamModel).delete(synchronize_session=False)
        session.query(AgentModel).delete(synchronize_session=False)
        session.query(ManagerConfigModel).delete(synchronize_session=False)

    @staticmethod
    def _write_deletions(session: Any, snapshot: Dict[str, Any]) -> None:
        for lib_id in snapshot.get("deleted_libraries", ()):
            session.query(DocLibLinkModel).filter(
                (DocLibLinkModel.source_lib_id == lib_id)
                | (DocLibLinkModel.target_lib_id == lib_id)
            ).delete(synchronize_session=False)
            session.query(LibraryPermissionModel).filter_by(lib_id=lib_id).delete(
                synchronize_session=False
            )
            session.query(DocLibFileModel).filter_by(lib_id=lib_id).delete(
                synchronize_session=False
            )
            session.query(LibraryModel).filter_by(lib_id=lib_id).delete(synchronize_session=False)
        for agent_id in snapshot.get("deleted_agents", ()):
            session.execute(delete(team_members).where(team_members.c.agent_id == agent_id))
            session.query(AgentMessageModel).filter_by(agent_id=agent_id).delete(
                synchronize_session=False
            )
            session.query(AgentModel).filter_by(agent_id=agent_id).delete(synchronize_session=False)

    @staticmethod
    def _write_configs(session: Any, configs: Optional[Dict[str, str]]) -> None:
        if configs is None:
            return
        for key, value in configs.items():
            session.merge(ManagerConfigModel(config_key=key, config_value=value))

    @staticmethod
    def _write_agents(session: Any, agents: Iterable[Dict[str, Any]]) -> None:
        for agent in agents:
            session.merge(
                AgentModel(
                    agent_id=agent["agent_id"],
                    name=agent["name"],
                    role=agent["role"],
                    role_description=agent["role_description"],
                    system_instructions=agent["system_instructions"],
                    model_alias=agent["model_alias"],
                    last_context=agent["last_context"],
                    lifecycle_state=agent["lifecycle_state"],
                )
            )
            session.query(AgentMessageModel).filter_by(agent_id=agent["agent_id"]).delete(
                synchronize_session=False
            )
            for index, message in enumerate(agent["messages"]):
                session.add(
                    AgentMessageModel(
                        agent_id=agent["agent_id"],
                        role=message.get("role", "user"),
                        content=message.get("content"),
                        tool_calls=message.get("tool_calls"),
                        tool_call_id=message.get("tool_call_id"),
                        name=message.get("name"),
                        team_id=message.get("team_id"),
                        discussion_id=message.get("discussion_id"),
                        created_at=agent["message_timestamp"] + index * 0.001,
                    )
                )

    @staticmethod
    def _write_teams(session: Any, teams: Iterable[Dict[str, Any]]) -> None:
        teams = list(teams)
        for team in teams:
            session.merge(
                TeamModel(
                    team_id=team["team_id"],
                    preset_name=team["preset_name"],
                    team_purpose=team["team_purpose"],
                    team_progress=team["team_progress"],
                    depth=team["depth"],
                    chapter_num=team["chapter_num"],
                    parent_team_id=None,
                    migration_count=team["migration_count"],
                    creator_agent_id=(
                        team["creator_id"] if team["creator_type"] == "agent" else None
                    ),
                    creator_team_id=(
                        team["creator_id"] if team["creator_type"] == "team" else None
                    ),
                    status_map=team["status_map"],
                    system_instructions=team["system_instructions"],
                )
            )
        session.flush()
        for team in teams:
            session.query(TeamModel).filter_by(team_id=team["team_id"]).update(
                {"parent_team_id": team["parent_team_id"]},
                synchronize_session=False,
            )
        session.flush()
        for team in teams:
            session.execute(delete(team_members).where(team_members.c.team_id == team["team_id"]))
            for member_id in team["members"]:
                session.execute(
                    team_members.insert().values(team_id=team["team_id"], agent_id=member_id)
                )

    @staticmethod
    def _write_inboxes(session: Any, inboxes: Dict[str, Dict[str, Any]]) -> None:
        for team_id, inbox in inboxes.items():
            session.query(TeamInboxModel).filter_by(team_id=team_id).delete(
                synchronize_session=False
            )
            for index, message in enumerate(inbox["messages"]):
                session.add(
                    TeamInboxModel(
                        team_id=team_id,
                        sender=message.get("from", "Unknown"),
                        msg_type=message.get("type", "Unknown"),
                        payload=json.dumps(message),
                        created_at=(inbox["message_timestamp"] + index * 0.001),
                    )
                )

    @staticmethod
    def _write_proposals(session: Any, proposals: Dict[str, List[Dict[str, Any]]]) -> None:
        for team_id, team_proposals in proposals.items():
            session.query(TeamProposalModel).filter_by(team_id=team_id).delete(
                synchronize_session=False
            )
            for proposal in team_proposals:
                session.add(
                    TeamProposalModel(
                        proposal_id=proposal["proposal_id"],
                        team_id=team_id,
                        action=proposal.get("action"),
                        target=proposal.get("target"),
                        initiator_type=proposal.get("initiator_type"),
                        initiator_name=proposal.get("initiator_name"),
                        initiator_agent_id=proposal.get("initiator_agent_id"),
                        rationale=proposal.get("rationale"),
                        proposed_details=json.dumps(proposal.get("proposed_details", {})),
                        votes=json.dumps(proposal.get("votes", {})),
                        status=proposal.get("status"),
                    )
                )

    @staticmethod
    def _write_communication_requests(session: Any, requests: Iterable[Dict[str, Any]]) -> None:
        for request in requests:
            session.merge(
                CommunicationRequestModel(
                    request_id=request["request_id"],
                    sender_team_id=request["sender_team_id"],
                    recipient_team_id=request["recipient_team_id"],
                    initiated_by_agent_id=request.get("initiated_by_agent_id"),
                    rationale=request["rationale"],
                    direction=request["direction"],
                    policy_snapshot=request["policy_snapshot"],
                    approval_principals=request["approval_principals"],
                    route_fingerprint=request["route_fingerprint"],
                    status=request["status"],
                    decision_reason=request.get("decision_reason", ""),
                    created_at=request["created_at"],
                    resolved_at=request.get("resolved_at"),
                    superseded_by_request_id=request.get("superseded_by_request_id"),
                    supersedes_request_id=request.get("supersedes_request_id"),
                )
            )

    @staticmethod
    def _write_communication_approvals(
        session: Any,
        approvals: Iterable[Dict[str, Any]],
        ballots: Iterable[Dict[str, Any]],
    ) -> None:
        request_ids = {approval["request_id"] for approval in approvals}
        for request_id in request_ids:
            session.query(CommunicationBallotModel).filter_by(request_id=request_id).delete(
                synchronize_session=False
            )
            session.query(CommunicationApprovalModel).filter_by(request_id=request_id).delete(
                synchronize_session=False
            )
        for approval in approvals:
            principal = approval["principal"]
            session.add(
                CommunicationApprovalModel(
                    request_id=approval["request_id"],
                    principal_kind=principal["kind"],
                    principal_id=principal["principal_id"],
                    sequence=approval["sequence"],
                    status=approval["status"],
                    reason=approval.get("reason", ""),
                    created_at=approval["created_at"],
                    resolved_at=approval.get("resolved_at"),
                )
            )
        session.flush()
        for ballot in ballots:
            if ballot["request_id"] not in request_ids:
                continue
            principal = ballot["principal"]
            session.add(
                CommunicationBallotModel(
                    request_id=ballot["request_id"],
                    principal_kind=principal["kind"],
                    principal_id=principal["principal_id"],
                    voter_agent_id=ballot["voter_agent_id"],
                    approved=int(ballot["approved"]),
                    reason=ballot.get("reason", ""),
                    created_at=ballot["created_at"],
                )
            )

    @staticmethod
    def _write_communication_agreements(session: Any, agreements: Iterable[Dict[str, Any]]) -> None:
        for agreement in agreements:
            session.merge(
                CommunicationAgreementModel(
                    agreement_id=agreement["agreement_id"],
                    source_team_id=agreement["source_team_id"],
                    target_team_id=agreement["target_team_id"],
                    direction=agreement["direction"],
                    allowed_message_types=agreement["allowed_message_types"],
                    created_from_request_id=agreement["created_from_request_id"],
                    policy_snapshot=agreement["policy_snapshot"],
                    active=int(agreement["active"]),
                    created_at=agreement["created_at"],
                    revoked_at=agreement.get("revoked_at"),
                    revoked_by_team_id=agreement.get("revoked_by_team_id"),
                    revoke_reason=agreement.get("revoke_reason"),
                    superseded_by_agreement_id=agreement.get("superseded_by_agreement_id"),
                )
            )

    @staticmethod
    def _write_peer_messages(session: Any, messages: Iterable[Dict[str, Any]]) -> None:
        for message in messages:
            session.merge(
                PeerMessageModel(
                    message_id=message["message_id"],
                    sender_team_id=message["sender_team_id"],
                    recipient_team_id=message["recipient_team_id"],
                    initiated_by_agent_id=message.get("initiated_by_agent_id"),
                    agreement_id=message.get("agreement_id"),
                    content=message["content"],
                    delivery_state=message["delivery_state"],
                    created_at=message["created_at"],
                    consumed_at=message.get("consumed_at"),
                    invocation_id=message.get("invocation_id"),
                )
            )

    @staticmethod
    def _write_libraries(session: Any, libraries: Iterable[Dict[str, Any]]) -> None:
        for library in libraries:
            session.merge(
                LibraryModel(
                    lib_id=library["lib_id"],
                    name=library["name"],
                    owner_team_id=library["owner_team_id"],
                    owner_agent_id=library.get("owner_agent_id"),
                    library_kind=library.get("library_kind", "team"),
                    lifecycle_state=library.get("lifecycle_state", "active"),
                    description=library["description"],
                    is_public_visible=int(library["is_public_visible"]),
                )
            )

    @staticmethod
    def _write_permissions(
        session: Any,
        permissions: Dict[str, Dict[str, Dict[str, str]]],
    ) -> None:
        for lib_id, path_map in permissions.items():
            session.query(LibraryPermissionModel).filter_by(lib_id=lib_id).delete(
                synchronize_session=False
            )
            for path, team_map in path_map.items():
                for team_id, permission in team_map.items():
                    session.add(
                        LibraryPermissionModel(
                            lib_id=lib_id,
                            path=path,
                            team_id=team_id,
                            permission=permission,
                        )
                    )

    @staticmethod
    def _write_file_changes(
        session: Any, file_changes: Dict[str, Dict[str, Optional[str]]]
    ) -> None:
        for lib_id, changes in file_changes.items():
            for path, content in changes.items():
                session.query(DocLibFileModel).filter_by(lib_id=lib_id, path=path).delete(
                    synchronize_session=False
                )
                if content is not None:
                    session.add(
                        DocLibFileModel(
                            lib_id=lib_id,
                            path=path,
                            content=content,
                        )
                    )

    @staticmethod
    def _write_links(
        session: Any,
        links: Optional[Dict[str, Dict[str, Dict[str, str]]]],
    ) -> None:
        if links is None:
            return
        for source_lib_id, path_map in links.items():
            session.query(DocLibLinkModel).filter_by(source_lib_id=source_lib_id).delete(
                synchronize_session=False
            )
            for source_path, target in path_map.items():
                session.add(
                    DocLibLinkModel(
                        source_lib_id=source_lib_id,
                        source_path=source_path,
                        target_lib_id=target["target_lib_id"],
                        target_path=target["target_path"],
                    )
                )
