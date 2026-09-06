"""Full-snapshot cleanup and explicit entity deletion."""

from typing import Any, Dict

from sqlalchemy import delete, text

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
    TeamInboxModel,
    TeamModel,
    TeamProposalModel,
    team_members,
)


class CleanupWriteMixin:
    @staticmethod
    def _clear_all(session: Any) -> None:
        for model in (
            RetainedMemoryReferenceModel,
            MemoryCardTagModel,
            MemoryCardSourceEventModel,
            AgentMemoryCardModel,
            AgentMemorySegmentModel,
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
        for reference_id in snapshot.get("deleted_memory_references", ()):
            session.query(RetainedMemoryReferenceModel).filter_by(
                reference_id=reference_id
            ).delete(synchronize_session=False)
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
            fts_exists = session.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='agent_memory_cards_fts'"
                )
            ).first()
            if fts_exists:
                session.execute(
                    text("DELETE FROM agent_memory_cards_fts WHERE agent_id = :agent_id"),
                    {"agent_id": agent_id},
                )
            session.execute(delete(team_members).where(team_members.c.agent_id == agent_id))
            session.query(AgentMessageModel).filter_by(agent_id=agent_id).delete(
                synchronize_session=False
            )
            session.query(AgentModel).filter_by(agent_id=agent_id).delete(synchronize_session=False)
