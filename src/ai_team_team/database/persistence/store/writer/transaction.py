"""Transactional orchestration for full and incremental ATT state writes."""

from typing import Any, Callable, Dict

from sqlalchemy import text
from ..records import read_receipt, write_records, write_receipts

from .cleanup import CleanupWriteMixin
from .acceptance_time import AcceptanceTimeWriteMixin
from .communication import CommunicationWriteMixin
from .core_state import CoreStateWriteMixin
from .formations import FormationWriteMixin
from .governance import GovernanceWriteMixin
from .libraries import LibraryWriteMixin
from .memory import MemoryWriteMixin


class StoreWriteMixin(
    AcceptanceTimeWriteMixin,
    CleanupWriteMixin,
    MemoryWriteMixin,
    CoreStateWriteMixin,
    CommunicationWriteMixin,
    FormationWriteMixin,
    GovernanceWriteMixin,
    LibraryWriteMixin,
):
    session_factory: Any
    _materialize: Callable[[Dict[str, Any]], Dict[str, Any]]

    def write(self, snapshot: Dict[str, Any], *, acceptance_reader=None):
        """Writes a full snapshot or an incremental immutable delta."""
        self._validation.check_file_identity()
        self._preflight_schema(self.db_path)
        snapshot = self._materialize(snapshot)
        session = self.session_factory()
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            session.execute(text("PRAGMA defer_foreign_keys = ON"))
            self._validation.begin(session, full=bool(snapshot["full"]))
            if snapshot.get("_publication_rollback"):
                from ..publication_rollback import discard_provisional_records
                discard_provisional_records(session, snapshot["_publication_rollback"])
            if snapshot["full"]:
                session.execute(text("PRAGMA defer_foreign_keys = ON"))
                self._clear_all(session)

            self._write_deletions(session, snapshot)

            self._write_configs(session, snapshot.get("configs"))
            session.execute(text("INSERT INTO manager_config(config_key, config_value) VALUES('state_version', :version) ON CONFLICT(config_key) DO UPDATE SET config_value = MAX(CAST(config_value AS INTEGER), CAST(:version AS INTEGER))"), {"version": str(max(1, snapshot.get("state_version", 1)))})
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
            team_dependencies = self._missing_team_dependencies(
                session, snapshot.get("team_dependencies", [])
            )
            self._write_teams(session, team_dependencies + snapshot.get("teams", []), snapshot.get("records", ()))
            session.flush()
            self._write_formation_requests(
                session, snapshot.get("formation_requests", [])
            )
            session.flush()
            self._write_formation_revisions(
                session, snapshot.get("formation_revisions", [])
            )
            self._write_formation_decisions(
                session, snapshot.get("formation_decisions", [])
            )
            self._write_formation_drafts(
                session, snapshot.get("formation_drafts", [])
            )
            self._write_formation_invitations(
                session,
                snapshot.get("formation_invitations", []),
                snapshot.get("formation_invitation_request_ids", []),
            )
            self._write_agent_inboxes(session, snapshot.get("agent_inboxes", {}))
            session.flush()
            self._write_agent_inbox_dependencies(session, snapshot.get("agent_inbox_dependencies", ()))
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
            self._write_governance(session, snapshot.get("governance_cases", []), snapshot.get("migration_requests", []), snapshot.get("state_version", 1))
            self._write_library_dependencies(session, snapshot.get("library_dependencies", []))
            self._write_libraries(session, snapshot.get("libraries", []))
            session.flush()
            self._write_permissions(session, snapshot.get("permissions", {}))
            self._write_file_changes(session, snapshot.get("file_changes", {}))
            self._write_links(session, snapshot.get("links"))
            session.flush()
            write_records(session, snapshot.get("records", ()), read_compensations=snapshot.get("_read_compensations", ()))
            self._sync_current_memberships(session, snapshot.get("records", ()), team_dependencies + snapshot.get("teams", []))
            self._sync_current_topology(session, snapshot.get("records", ()), team_dependencies + snapshot.get("teams", []))
            candidate = self._validation.prepare(session)
            operations, timestamps = self._bind_acceptance_times(session, snapshot, acceptance_reader)
            receipts = write_receipts(session, operations)
            for receipt in receipts:
                if read_receipt(session, receipt.operation_id) != receipt:
                    raise RuntimeError("The stored receipt does not match the accepted operation.")
            if self._validation.has_triggers:
                # A trigger on receipt insertion may affect earlier domain
                # facts. Validate those effects before the real commit too.
                candidate = self._validation.prepare(session)
            session.commit()
            self._validation.finish(None if timestamps else candidate)
            return self._accepted_write(receipts, timestamps)
        except BaseException:
            self._validation.finish()
            session.rollback()
            raise
        finally:
            session.close()
