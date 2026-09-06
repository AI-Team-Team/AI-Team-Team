"""Detached reading of complete ATT state from SQLite."""

import json
from typing import Any, Dict

from sqlalchemy import text

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import (
    AgentMessageModel,
    AgentMemoryCardModel,
    AgentMemorySegmentModel,
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
    MemoryCardSourceEventModel,
    MemoryCardTagModel,
    PeerMessageModel,
    RetainedMemoryReferenceModel,
    SystemMemoryEventModel,
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

            episodic_enabled = bool(
                json.loads(config_map.get("att_config", "{}")).get(
                    "episodic_memory", {}
                ).get("enabled", False)
            )
            if episodic_enabled:
                fts_exists = session.execute(
                    text(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='agent_memory_cards_fts'"
                    )
                ).first()
                if not fts_exists:
                    raise StateRestoreError(
                        "The state enables selective episodic memory but its FTS5 index is missing."
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

            memory_events = [
                {
                    "event_id": row.event_id,
                    "sequence": row.sequence,
                    "event_type": row.event_type,
                    "agent_id": row.agent_id,
                    "agent_name_snapshot": row.agent_name_snapshot,
                    "team_id": row.team_id,
                    "discussion_id": row.discussion_id,
                    "turn_id": row.turn_id,
                    "role": row.role,
                    "payload": row.payload,
                    "redacted": bool(row.redacted),
                    "created_at": row.created_at,
                }
                for row in session.query(SystemMemoryEventModel)
                .order_by(SystemMemoryEventModel.sequence)
                .all()
            ]
            memory_segments = []
            for row in session.query(AgentMemorySegmentModel).all():
                source_event_ids = [
                    event_id
                    for (event_id,) in session.query(
                        MemoryCardSourceEventModel.event_id
                    )
                    .filter_by(segment_id=row.segment_id)
                    .order_by(MemoryCardSourceEventModel.sequence)
                    .all()
                ]
                memory_segments.append(
                    {
                        "segment_id": row.segment_id,
                        "agent_id": row.agent_id,
                        "turn_id": row.turn_id,
                        "origin_team_id": row.origin_team_id,
                        "discussion_id": row.discussion_id,
                        "source_event_ids": source_event_ids,
                        "recall_content": row.recall_content,
                        "content_sha256": row.content_sha256,
                        "status": row.status,
                        "attempts": row.attempts,
                        "last_error_kind": row.last_error_kind,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                    }
                )
            memory_cards = []
            for row in session.query(AgentMemoryCardModel).all():
                tags = [
                    tag
                    for (tag,) in session.query(MemoryCardTagModel.tag)
                    .filter_by(memory_id=row.memory_id)
                    .order_by(MemoryCardTagModel.sequence)
                    .all()
                ]
                memory_cards.append(
                    {
                        "memory_id": row.memory_id,
                        "agent_id": row.agent_id,
                        "turn_id": row.turn_id,
                        "title": row.title,
                        "summary": row.summary,
                        "tags": tags,
                        "origin_team_id": row.origin_team_id,
                        "discussion_id": row.discussion_id,
                        "segment_id": row.segment_id,
                        "status": row.status,
                        "version": row.version,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                    }
                )
            memory_references = [
                {
                    "reference_id": row.reference_id,
                    "agent_id": row.agent_id,
                    "memory_id": row.memory_id,
                    "note": row.note,
                    "created_at": row.created_at,
                }
                for row in session.query(RetainedMemoryReferenceModel).all()
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
                "memory_events": memory_events,
                "memory_segments": memory_segments,
                "memory_cards": memory_cards,
                "memory_references": memory_references,
            }
        finally:
            session.close()

    def search_memory_card_ids(
        self, agent_id: str, query: str, limit: int
    ) -> list[str]:
        """Returns owner-scoped FTS5 matches without exposing card content."""
        session = self.session_factory()
        try:
            exists = session.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='agent_memory_cards_fts'"
                )
            ).first()
            if not exists:
                raise StateRestoreError(
                    "Selective episodic memory requires its SQLite FTS5 index."
                )
            terms = [part for part in query.split() if part]
            expression = " AND ".join(
                f'"{part.replace(chr(34), chr(34) * 2)}"' for part in terms
            )
            if not expression:
                return []
            rows = session.execute(
                text(
                    "SELECT agent_memory_cards_fts.memory_id "
                    "FROM agent_memory_cards_fts "
                    "JOIN agent_memory_cards ON "
                    "agent_memory_cards.memory_id = agent_memory_cards_fts.memory_id "
                    "WHERE agent_memory_cards_fts MATCH :query "
                    "AND agent_memory_cards_fts.agent_id = :agent_id "
                    "AND agent_memory_cards.status = 'active' "
                    "ORDER BY rank LIMIT :limit"
                ),
                {"query": expression, "agent_id": agent_id, "limit": limit},
            ).all()
            return [row[0] for row in rows]
        finally:
            session.close()
