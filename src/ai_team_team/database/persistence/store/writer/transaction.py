"""Transactional orchestration for full and incremental ATT state writes."""

from typing import Any, Callable, Dict

from sqlalchemy import text

from .cleanup import CleanupWriteMixin
from .communication import CommunicationWriteMixin
from .core_state import CoreStateWriteMixin
from .libraries import LibraryWriteMixin
from .memory import MemoryWriteMixin


class StoreWriteMixin(
    CleanupWriteMixin,
    MemoryWriteMixin,
    CoreStateWriteMixin,
    CommunicationWriteMixin,
    LibraryWriteMixin,
):
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
            self._write_agent_dependencies(session, snapshot.get("agent_dependencies", []))
            self._write_agents(session, snapshot.get("agents", []))
            session.flush()
            self._write_memory_events(
                session,
                snapshot.get("memory_events", []),
                full=bool(snapshot["full"]),
            )
            session.flush()
            self._write_memory_segments(
                session, snapshot.get("memory_segments", [])
            )
            session.flush()
            self._write_memory_cards(
                session, snapshot.get("memory_cards", [])
            )
            self._write_memory_references(
                session, snapshot.get("memory_references", [])
            )
            self._sync_memory_fts(session, snapshot)
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
            self._write_library_dependencies(session, snapshot.get("library_dependencies", []))
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
