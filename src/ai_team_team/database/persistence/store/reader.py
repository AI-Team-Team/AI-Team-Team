"""Detached reading of complete ATT state from SQLite."""

import json
from typing import Any, Dict

from ai_team_team.core.exceptions import StateRestoreError
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
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION


class StoreReadMixin:
    session_factory: Any

    def read(self) -> Dict[str, Any]:
        """Reads all persisted state into detached plain Python structures."""
        session = self.session_factory()
        try:
            config_map = {
                row.config_key: row.config_value for row in session.query(ManagerConfigModel).all()
            }
            version = config_map.get("schema_version")
            if version != STATE_SCHEMA_VERSION:
                raise StateRestoreError(
                    f"Unsupported state schema version {version!r}; "
                    f"expected {STATE_SCHEMA_VERSION!r}."
                )

            agents = []
            for row in session.query(AgentModel).all():
                messages = []
                message_rows = (
                    session.query(AgentMessageModel)
                    .filter_by(agent_id=row.agent_id)
                    .order_by(AgentMessageModel.created_at, AgentMessageModel.id)
                    .all()
                )
                for msg in message_rows:
                    messages.append(
                        {
                            "role": msg.role,
                            "content": msg.content,
                            "tool_calls": msg.tool_calls,
                            "tool_call_id": msg.tool_call_id,
                            "name": msg.name,
                            "team_id": msg.team_id,
                            "discussion_id": msg.discussion_id,
                        }
                    )
                agents.append(
                    {
                        "agent_id": row.agent_id,
                        "name": row.name,
                        "role": row.role,
                        "role_description": row.role_description,
                        "system_instructions": row.system_instructions,
                        "model_alias": row.model_alias,
                        "last_context": row.last_context,
                        "lifecycle_state": row.lifecycle_state,
                        "messages": messages,
                    }
                )

            teams = []
            for row in session.query(TeamModel).all():
                member_names = [
                    agent_id
                    for (agent_id,) in session.query(team_members.c.agent_id)
                    .filter(team_members.c.team_id == row.team_id)
                    .all()
                ]
                inbox = []
                for msg in (
                    session.query(TeamInboxModel)
                    .filter_by(team_id=row.team_id)
                    .order_by(TeamInboxModel.created_at, TeamInboxModel.id)
                    .all()
                ):
                    inbox.append(json.loads(msg.payload))
                proposals = []
                for proposal in session.query(TeamProposalModel).filter_by(team_id=row.team_id):
                    proposals.append(
                        {
                            "proposal_id": proposal.proposal_id,
                            "action": proposal.action,
                            "target": proposal.target,
                            "initiator_type": proposal.initiator_type,
                            "initiator_name": proposal.initiator_name,
                            "initiator_agent_id": proposal.initiator_agent_id,
                            "rationale": proposal.rationale,
                            "proposed_details": json.loads(proposal.proposed_details or "{}"),
                            "votes": json.loads(proposal.votes or "{}"),
                            "status": proposal.status,
                        }
                    )
                teams.append(
                    {
                        "team_id": row.team_id,
                        "preset_name": row.preset_name,
                        "team_purpose": row.team_purpose,
                        "team_progress": row.team_progress,
                        "depth": row.depth,
                        "chapter_num": row.chapter_num,
                        "parent_team_id": row.parent_team_id,
                        "migration_count": row.migration_count,
                        "creator_type": ("agent" if row.creator_agent_id else "team"),
                        "creator_id": (row.creator_agent_id or row.creator_team_id),
                        "status_map": row.status_map,
                        "system_instructions": row.system_instructions,
                        "members": member_names,
                        "inbox": inbox,
                        "proposals": proposals,
                    }
                )

            libraries = []
            for row in session.query(LibraryModel).all():
                files = {
                    file_row.path: file_row.content
                    for file_row in session.query(DocLibFileModel).filter_by(lib_id=row.lib_id)
                }
                libraries.append(
                    {
                        "lib_id": row.lib_id,
                        "name": row.name,
                        "owner_team_id": row.owner_team_id,
                        "owner_agent_id": row.owner_agent_id,
                        "library_kind": row.library_kind,
                        "lifecycle_state": row.lifecycle_state,
                        "description": row.description,
                        "is_public_visible": bool(row.is_public_visible),
                        "files": files,
                    }
                )

            permissions: Dict[str, Dict[str, Dict[str, str]]] = {}
            for row in session.query(LibraryPermissionModel).all():
                permissions.setdefault(row.lib_id, {}).setdefault(row.path, {})[row.team_id] = (
                    row.permission
                )

            links: Dict[str, Dict[str, Dict[str, str]]] = {}
            for row in session.query(DocLibLinkModel).all():
                links.setdefault(row.source_lib_id, {})[row.source_path] = {
                    "target_lib_id": row.target_lib_id,
                    "target_path": row.target_path,
                }

            communication_requests = [
                {
                    "request_id": row.request_id,
                    "sender_team_id": row.sender_team_id,
                    "recipient_team_id": row.recipient_team_id,
                    "initiated_by_agent_id": row.initiated_by_agent_id,
                    "rationale": row.rationale,
                    "direction": row.direction,
                    "policy_snapshot": row.policy_snapshot,
                    "approval_principals": row.approval_principals,
                    "route_fingerprint": row.route_fingerprint,
                    "status": row.status,
                    "decision_reason": row.decision_reason,
                    "created_at": row.created_at,
                    "resolved_at": row.resolved_at,
                    "superseded_by_request_id": row.superseded_by_request_id,
                    "supersedes_request_id": row.supersedes_request_id,
                }
                for row in session.query(CommunicationRequestModel).all()
            ]
            communication_approvals = [
                {
                    "request_id": row.request_id,
                    "principal": {
                        "kind": row.principal_kind,
                        "principal_id": row.principal_id,
                    },
                    "sequence": row.sequence,
                    "status": row.status,
                    "reason": row.reason,
                    "created_at": row.created_at,
                    "resolved_at": row.resolved_at,
                }
                for row in session.query(CommunicationApprovalModel).all()
            ]
            communication_ballots = [
                {
                    "request_id": row.request_id,
                    "principal": {
                        "kind": row.principal_kind,
                        "principal_id": row.principal_id,
                    },
                    "voter_agent_id": row.voter_agent_id,
                    "approved": bool(row.approved),
                    "reason": row.reason,
                    "created_at": row.created_at,
                }
                for row in session.query(CommunicationBallotModel).all()
            ]
            communication_agreements = [
                {
                    "agreement_id": row.agreement_id,
                    "source_team_id": row.source_team_id,
                    "target_team_id": row.target_team_id,
                    "direction": row.direction,
                    "allowed_message_types": row.allowed_message_types,
                    "created_from_request_id": row.created_from_request_id,
                    "policy_snapshot": row.policy_snapshot,
                    "active": bool(row.active),
                    "created_at": row.created_at,
                    "revoked_at": row.revoked_at,
                    "revoked_by_team_id": row.revoked_by_team_id,
                    "revoke_reason": row.revoke_reason,
                    "superseded_by_agreement_id": row.superseded_by_agreement_id,
                }
                for row in session.query(CommunicationAgreementModel).all()
            ]
            peer_messages = [
                {
                    "message_id": row.message_id,
                    "sender_team_id": row.sender_team_id,
                    "recipient_team_id": row.recipient_team_id,
                    "initiated_by_agent_id": row.initiated_by_agent_id,
                    "agreement_id": row.agreement_id,
                    "content": row.content,
                    "delivery_state": row.delivery_state,
                    "created_at": row.created_at,
                    "consumed_at": row.consumed_at,
                    "invocation_id": row.invocation_id,
                }
                for row in session.query(PeerMessageModel).all()
            ]

            return {
                "configs": config_map,
                "agents": agents,
                "teams": teams,
                "libraries": libraries,
                "permissions": permissions,
                "links": links,
                "communication_requests": communication_requests,
                "communication_approvals": communication_approvals,
                "communication_ballots": communication_ballots,
                "communication_agreements": communication_agreements,
                "peer_messages": peer_messages,
            }
        finally:
            session.close()
