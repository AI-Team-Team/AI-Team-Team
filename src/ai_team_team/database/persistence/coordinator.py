"""Asynchronous single-writer coordination and delta coalescing."""

import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional, cast

from .lease import WriterLease
from .store import DatabaseStore


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
                self._leases[resolved] = WriterLease(resolved)

    def submit(self, db_path: str, snapshot: Dict[str, Any]) -> Future[Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Persistence coordinator is closed.")
            self.claim(db_path)
            resolved = str(Path(db_path).resolve())
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

    async def read(self, db_path: str) -> Dict[str, Any]:
        self.claim(db_path)
        await self.flush()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._read, db_path)

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
            for store in self._stores.values():
                store.close()
            self._executor.shutdown(wait=True)
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

    def _write(self, db_path: str, snapshot: Dict[str, Any]) -> None:
        capture_error = snapshot.get("_capture_error")
        if capture_error is not None:
            raise capture_error
        self._store(db_path).write(snapshot)

    def _read(self, db_path: str) -> Dict[str, Any]:
        return self._store(db_path).read()

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
                    completion.set_result(None)
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
        """Coalesces immutable deltas without losing later entity values."""
        if later.get("_capture_error") is not None:
            return later
        if earlier.get("_capture_error") is not None:
            return earlier
        if later.get("full"):
            return later
        merged = dict(earlier)
        merged["full"] = bool(earlier.get("full"))
        merged["state_version"] = later.get("state_version", earlier.get("state_version"))
        if later.get("configs") is not None:
            merged["configs"] = later["configs"]
        for key, identity in (
            ("agents", "agent_id"),
            ("teams", "team_id"),
            ("libraries", "lib_id"),
            ("communication_requests", "request_id"),
            ("communication_agreements", "agreement_id"),
            ("peer_messages", "message_id"),
        ):
            records = {record[identity]: record for record in earlier.get(key, [])}
            records.update({record[identity]: record for record in later.get(key, [])})
            merged[key] = list(records.values())

        for dependency_key, authoritative_key, identity in (
            ("agent_dependencies", "agents", "agent_id"),
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

        for key in ("inboxes", "proposals", "permissions", "links"):
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
        merged["deleted_libraries"] = list(
            set(earlier.get("deleted_libraries", ())) | set(later.get("deleted_libraries", ()))
        )
        deleted_agents = set(merged["deleted_agents"])
        deleted_libraries = set(merged["deleted_libraries"])
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
        merged["library_dependencies"] = [
            record
            for record in merged.get("library_dependencies", [])
            if record["lib_id"] not in deleted_libraries
        ]
        for key in ("permissions", "links", "file_changes"):
            merged[key] = {
                lib_id: value
                for lib_id, value in merged.get(key, {}).items()
                if lib_id not in deleted_libraries
            }
        return merged
