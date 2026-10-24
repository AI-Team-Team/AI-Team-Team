"""Asynchronous single-writer coordination and delta coalescing."""

import asyncio
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional, cast

from ai_team_team.core.exceptions import StateRestoreError

from .lease import WriterLease
from .store import DatabaseStore
from .records import merge_records
from .receipts import CommitReceipt, settle_commit


class PersistenceCoordinator:
    """Runs one write and coalesces all later deltas into one pending write."""

    def __init__(self, db_path: Optional[str] = None):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="att-state-writer")
        self._stores: Dict[str, DatabaseStore] = {}
        self._leases: Dict[str, WriterLease] = {}
        self._active_task: Optional[Future[Any]] = None
        self._active_completion: Optional[Future[Any]] = None
        self._pending_path: Optional[str] = None
        self._pending_snapshot: Optional[Dict[str, Any]] = None
        self._pending_completion: Optional[Future[Any]] = None
        self._error: Optional[BaseException] = None
        self._lock = threading.RLock()
        self._closed = False
        self._prepared_paths = set()
        self._acceptance_clocks = {}
        if db_path:
            try:
                self.claim(db_path)
            except Exception:
                self._executor.shutdown(wait=False)
                raise

    def claim(self, db_path: str) -> None:
        """Acquires this manager's exclusive writer lease immediately."""
        resolved = str(Path(db_path).resolve())
        with self._lock:
            if self._closed:
                raise RuntimeError("Persistence coordinator is closed.")
            if resolved not in self._leases:
                lease = WriterLease(resolved)
                try:
                    DatabaseStore._preflight_schema(resolved)
                except BaseException:
                    lease.close()
                    raise
                self._leases[resolved] = lease

    async def prepare_runtime(self, db_path):
        """Reconcile crash-left publication before any external mutation is admitted."""
        self.claim(db_path)
        await self.flush()
        # Reconciliation can rename directories and commit rollback evidence.
        # Cancellation must not outlive its caller's admission protection.
        await settle_commit(asyncio.get_running_loop().run_in_executor(self._executor, self._prepare, db_path))

    def _prepare(self, db_path):
        resolved = str(Path(db_path).resolve())
        if resolved not in self._prepared_paths:
            from .store.reconciliation import reconcile_publication
            reconcile_publication(self._store(resolved))
            self._prepared_paths.add(resolved)

    def submit(self, db_path: str, snapshot: Dict[str, Any], *, acceptance_clock=None) -> Future[Any]:
        snapshot = dict(snapshot)
        if "_operations" not in snapshot and "_capture_error" not in snapshot:
            snapshot["_operations"] = (CommitReceipt(
                uuid.uuid4().hex, max(1, snapshot.get("state_version", 1)), "durable",
                tuple(record.receipt_key for record in snapshot.get("records", ())),
            ),)
        with self._lock:
            if self._closed:
                raise RuntimeError("Persistence coordinator is closed.")
            self.claim(db_path)
            bindings = tuple(snapshot.get("_acceptance_times", ()))
            owners = {binding.operation_id for binding in bindings}
            if len(owners) != len(bindings) or owners.intersection(self._acceptance_clocks):
                raise ValueError("A timed operation already owns its acceptance clock.")
            if snapshot.get("_acceptance_times"):
                if acceptance_clock is None:
                    raise ValueError("Timed publication requires its registered runtime clock.")
                from .acceptance_time import AcceptanceClockSource
                source = AcceptanceClockSource(asyncio.get_running_loop(), acceptance_clock)
                for binding in snapshot["_acceptance_times"]:
                    self._acceptance_clocks[binding.operation_id] = source
            resolved = str(Path(db_path).resolve())
            try:
                if self._active_task is None:
                    completion: Future[Any] = Future()
                    self._start_locked(resolved, snapshot, completion)
                    return completion
                if self._pending_snapshot is None:
                    self._pending_path = resolved
                    self._pending_snapshot = snapshot
                    self._pending_completion = Future()
                else:
                    if self._pending_path != resolved:
                        raise RuntimeError("Cannot queue deltas for different databases before flush.")
                    self._pending_snapshot = self._merge_snapshots(self._pending_snapshot, snapshot)
                return cast(Future[Any], self._pending_completion)
            except BaseException:
                for owner in owners:
                    self._acceptance_clocks.pop(owner, None)
                raise

    async def read(self, db_path: str, *, reconcile: bool = True) -> Dict[str, Any]:
        self.claim(db_path)
        await self.flush()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, self._read, db_path, reconcile)
        if reconcile:
            # Keep restore's resource gate held until this mutating worker has
            # finished, even after repeated cancellation of the observer.
            return await settle_commit(future)
        return await future

    async def receipt(self, db_path: str, operation_id: str, *, wait_pending: bool = True):
        """Look up an accepted operation after its caller lost the response."""
        self.claim(db_path)
        if wait_pending:
            await self.flush()
        def read():
            from .store.records import read_receipt
            with self._store(db_path).session_factory() as session:
                return read_receipt(session, operation_id)
        return await asyncio.get_running_loop().run_in_executor(self._executor, read)

    async def validate_restore_journal(self, db_path: str, events) -> None:
        """Read after accepted writes without poisoning the writer on rejection."""
        self.claim(db_path)
        await self.flush()
        await asyncio.get_running_loop().run_in_executor(
            self._executor, self._validate_restore_journal, db_path, tuple(events)
        )

    def _validate_restore_journal(self, db_path: str, events) -> None:
        resolved = str(Path(db_path).resolve())
        if DatabaseStore._preflight_schema(resolved):
            return  # An absent or empty target has no committed Journal.
        self._store(resolved).validate_restore_journal(events)

    async def search_memory_card_ids(
        self, db_path: str, agent_id: str, query: str, limit: int
    ) -> list[str]:
        """Flushes accepted deltas and executes an owner-scoped FTS query."""
        self.claim(db_path)
        await self.flush()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._search_memory_card_ids,
            db_path,
            agent_id,
            query,
            limit,
        )

    async def flush(self) -> None:
        while True:
            with self._lock:
                futures = tuple(
                    future
                    for future in (
                        self._active_completion,
                        self._pending_completion,
                    )
                    if future is not None
                )
            if not futures:
                break
            await asyncio.gather(
                *(asyncio.shield(asyncio.wrap_future(future)) for future in futures),
                return_exceptions=True,
            )
        with self._lock:
            error = self._error
        if error is not None:
            raise error

    async def close(self) -> None:
        if self._closed:
            return
        flush_error: Optional[Exception] = None
        try:
            await self.flush()
        except Exception as exc:
            flush_error = exc
        self._closed = True
        loop = asyncio.get_running_loop()

        def close_all() -> None:
            # Already accepted reads/preparation may still create or use a
            # store. Finish those workers before disposing every engine.
            self._executor.shutdown(wait=True)
            for store in self._stores.values():
                store.close()
            for lease in self._leases.values():
                lease.close()

        await loop.run_in_executor(None, close_all)
        if flush_error is not None:
            raise flush_error

    def _store(self, db_path: str) -> DatabaseStore:
        resolved = str(Path(db_path).resolve())
        with self._lock:
            store = self._stores.get(resolved)
            if store is None:
                store = DatabaseStore(resolved)
                self._stores[resolved] = store
            return store

    def _write(self, db_path: str, snapshot: Dict[str, Any]):
        try:
            capture_error = snapshot.get("_capture_error")
            if capture_error is not None:
                raise capture_error
            if not snapshot.get("_publication_operation"):
                self._prepare(db_path)
            if snapshot.get("_acceptance_times"):
                return self._store(db_path).write(snapshot, acceptance_reader=self._acceptance_time)
            return self._store(db_path).write(snapshot)
        finally:
            with self._lock:
                for binding in snapshot.get("_acceptance_times", ()):
                    self._acceptance_clocks.pop(binding.operation_id, None)

    def _acceptance_time(self, operation_id):
        with self._lock:
            source = self._acceptance_clocks[operation_id]
        return source.read()

    def _read(self, db_path: str, reconcile: bool = True) -> Dict[str, Any]:
        # A reader must never initialize or repair an empty source checkpoint.
        # Writable initialization remains exclusively on the write path.
        if DatabaseStore._preflight_schema(str(Path(db_path).resolve())):
            raise StateRestoreError("An empty database is not a restorable ATT checkpoint; it was not modified.")
        return self._store(db_path).read(reconcile=reconcile)

    def _search_memory_card_ids(
        self, db_path: str, agent_id: str, query: str, limit: int
    ) -> list[str]:
        return self._store(db_path).search_memory_card_ids(agent_id, query, limit)

    def _start_locked(
        self,
        db_path: str,
        snapshot: Dict[str, Any],
        completion: Future[Any],
    ) -> None:
        self._active_completion = completion
        self._active_task = self._executor.submit(self._write, db_path, snapshot)
        self._active_task.add_done_callback(self._finish_active)

    def _finish_active(self, task: Future[Any]) -> None:
        exception = task.exception()
        with self._lock:
            completion = self._active_completion
            if exception is None:
                if completion is not None and not completion.done():
                    completion.set_result(task.result())
            else:
                if self._error is None:
                    self._error = exception
                if completion is not None and not completion.done():
                    completion.set_exception(exception)

            self._active_task = None
            self._active_completion = None
            if self._pending_snapshot is not None:
                path = cast(str, self._pending_path)
                snapshot = self._pending_snapshot
                pending_completion = cast(Future[Any], self._pending_completion)
                self._pending_path = None
                self._pending_snapshot = None
                self._pending_completion = None
                self._start_locked(path, snapshot, pending_completion)

    @staticmethod
    def _merge_snapshots(earlier: Dict[str, Any], later: Dict[str, Any]) -> Dict[str, Any]:
        """Coalesce immutable deltas in state-version order, not arrival order."""
        if earlier.get("_publication_operation") or later.get("_publication_operation"):
            raise RuntimeError("A publication decision cannot coalesce with another authority operation.")
        acceptance_times = tuple(earlier.get("_acceptance_times", ())) + tuple(later.get("_acceptance_times", ()))
        if later.get("_capture_error") is not None:
            return {**later, "_acceptance_times": acceptance_times}
        if earlier.get("_capture_error") is not None:
            return {**earlier, "_acceptance_times": acceptance_times}
        if earlier.get("state_version", 1) > later.get("state_version", 1):
            earlier, later = later, earlier
        read_compensations = tuple(earlier.get("_read_compensations", ())) + tuple(later.get("_read_compensations", ()))
        if later.get("full"):
            merged = dict(later)
            merged["_acceptance_times"] = acceptance_times
            merged["records"] = merge_records(earlier.get("records", ()), later.get("records", ()), read_compensations=read_compensations)
            merged["_read_compensations"] = read_compensations
            merged["_operations"] = tuple(earlier.get("_operations", ())) + tuple(later.get("_operations", ()))
            for key in ("deleted_agents", "deleted_teams", "deleted_libraries", "deleted_memory_references"):
                merged[key] = tuple(set(earlier.get(key, ())) | set(later.get(key, ())))
            return merged
        merged = dict(earlier)
        merged["_acceptance_times"] = acceptance_times
        merged["full"] = bool(earlier.get("full"))
        merged["state_version"] = max(later.get("state_version", 1), earlier.get("state_version", 1))
        merged["records"] = merge_records(earlier.get("records", ()), later.get("records", ()), read_compensations=read_compensations)
        merged["_read_compensations"] = read_compensations
        merged["_operations"] = tuple(earlier.get("_operations", ())) + tuple(later.get("_operations", ()))
        merged["episodic_memory_enabled"] = later.get(
            "episodic_memory_enabled",
            earlier.get("episodic_memory_enabled", False),
        )
        if later.get("configs") is not None:
            merged["configs"] = later["configs"]
        for key, identity in (
            ("agents", "agent_id"),
            ("teams", "team_id"),
            ("libraries", "lib_id"),
            ("communication_requests", "request_id"),
            ("communication_agreements", "agreement_id"),
            ("peer_messages", "message_id"),
            ("formation_requests", "request_id"),
            ("formation_revisions", "revision_id"),
            ("formation_decisions", "decision_id"),
            ("formation_drafts", "draft_id"),
            ("governance_cases", "case_id"),
            ("migration_requests", "request_id"),
            ("agent_inbox_dependencies", "message_id"),
            ("memory_events", "event_id"),
            ("memory_segments", "segment_id"),
            ("memory_cards", "memory_id"),
            ("memory_references", "reference_id"),
        ):
            records = {record[identity]: record for record in earlier.get(key, [])}
            for record in later.get(key, []):
                previous = records.get(record[identity])
                previous_version = previous.get("state_version", earlier.get("state_version", 1)) if previous else 0
                if previous is None or record.get("state_version", later.get("state_version", 1)) >= previous_version:
                    records[record[identity]] = record
            merged[key] = list(records.values())

        for dependency_key, authoritative_key, identity in (
            ("agent_dependencies", "agents", "agent_id"),
            ("team_dependencies", "teams", "team_id"),
            ("library_dependencies", "libraries", "lib_id"),
        ):
            dependencies = {record[identity]: record for record in earlier.get(dependency_key, [])}
            dependencies.update(
                {record[identity]: record for record in later.get(dependency_key, [])}
            )
            authoritative_ids = {record[identity] for record in merged.get(authoritative_key, [])}
            merged[dependency_key] = [
                record
                for record_id, record in dependencies.items()
                if record_id not in authoritative_ids
            ]

        # Approval deltas always contain the complete Approval and ballot set
        # for each affected request. Replace that request as a unit so a retry
        # with no valid ballots can clear an earlier ballot set while writes
        # are being coalesced.
        replaced_approval_requests = {
            record["request_id"] for record in later.get("communication_approvals", [])
        }
        for key in (
            "communication_approvals",
            "communication_ballots",
        ):
            approval_records = [
                record
                for record in earlier.get(key, [])
                if record["request_id"] not in replaced_approval_requests
            ]
            approval_records.extend(later.get(key, []))
            merged[key] = approval_records

        replaced_formation_requests = set(
            later.get("formation_invitation_request_ids", ())
        )
        replaced_formation_requests.update(
            record["request_id"] for record in later.get("formation_invitations", [])
        )
        formation_invitations = [
            record
            for record in earlier.get("formation_invitations", [])
            if record["request_id"] not in replaced_formation_requests
        ]
        formation_invitations.extend(later.get("formation_invitations", []))
        merged["formation_invitations"] = formation_invitations
        merged["formation_invitation_request_ids"] = tuple(
            set(earlier.get("formation_invitation_request_ids", ()))
            | replaced_formation_requests
        )

        for key in ("inboxes", "agent_inboxes", "proposals", "permissions", "links"):
            records = dict(earlier.get(key, {}))
            records.update(later.get(key, {}))
            merged[key] = records

        file_changes = {
            lib_id: dict(changes) for lib_id, changes in earlier.get("file_changes", {}).items()
        }
        for lib_id, changes in later.get("file_changes", {}).items():
            file_changes.setdefault(lib_id, {}).update(changes)
        merged["file_changes"] = file_changes
        merged["deleted_agents"] = list(
            set(earlier.get("deleted_agents", ())) | set(later.get("deleted_agents", ()))
        )
        merged["deleted_teams"] = list(
            set(earlier.get("deleted_teams", ())) | set(later.get("deleted_teams", ()))
        )
        merged["deleted_libraries"] = list(
            set(earlier.get("deleted_libraries", ())) | set(later.get("deleted_libraries", ()))
        )
        merged["deleted_memory_references"] = list(
            set(earlier.get("deleted_memory_references", ()))
            | set(later.get("deleted_memory_references", ()))
        )
        deleted_agents = set(merged["deleted_agents"])
        deleted_teams = set(merged["deleted_teams"])
        deleted_libraries = set(merged["deleted_libraries"])
        merged["teams"] = [
            record for record in merged.get("teams", [])
            if record["team_id"] not in deleted_teams
        ]
        merged["agents"] = [
            record
            for record in merged.get("agents", [])
            if record["agent_id"] not in deleted_agents
        ]
        merged["libraries"] = [
            record
            for record in merged.get("libraries", [])
            if record["lib_id"] not in deleted_libraries
        ]
        merged["agent_dependencies"] = [
            record
            for record in merged.get("agent_dependencies", [])
            if record["agent_id"] not in deleted_agents
        ]
        merged["team_dependencies"] = [
            record
            for record in merged.get("team_dependencies", [])
            if record["team_id"] not in deleted_teams
        ]
        merged["agent_inboxes"] = {
            agent_id: inbox
            for agent_id, inbox in merged.get("agent_inboxes", {}).items()
            if agent_id not in deleted_agents
        }
        merged["agent_inbox_dependencies"] = [record for record in merged.get("agent_inbox_dependencies", ())
            if record["agent_id"] not in deleted_agents]
        for key in ("inboxes", "proposals"):
            merged[key] = {
                team_id: value
                for team_id, value in merged.get(key, {}).items()
                if team_id not in deleted_teams
            }
        for key in (
            "memory_segments",
            "memory_cards",
            "memory_references",
        ):
            merged[key] = [
                record
                for record in merged.get(key, [])
                if record["agent_id"] not in deleted_agents
            ]
        merged["library_dependencies"] = [
            record
            for record in merged.get("library_dependencies", [])
            if record["lib_id"] not in deleted_libraries
        ]
        deleted_references = set(merged["deleted_memory_references"])
        merged["memory_references"] = [
            record
            for record in merged.get("memory_references", [])
            if record["reference_id"] not in deleted_references
        ]
        for key in ("permissions", "links", "file_changes"):
            merged[key] = {
                lib_id: value
                for lib_id, value in merged.get(key, {}).items()
                if lib_id not in deleted_libraries
            }
        return merged
