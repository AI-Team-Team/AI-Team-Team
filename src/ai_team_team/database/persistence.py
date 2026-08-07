import asyncio
import json
import os
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine, delete, event, text
from sqlalchemy.orm import sessionmaker

from ai_team_team.core.exceptions import DatabaseOwnershipError, StateRestoreError
from ai_team_team.database.models import (
    Base,
    AgentMessageModel,
    AgentModel,
    BrokerAgreementModel,
    DocLibFileModel,
    DocLibLinkModel,
    LibraryModel,
    LibraryPermissionModel,
    ManagerConfigModel,
    TeamInboxModel,
    TeamModel,
    TeamProposalModel,
    team_members,
)


STATE_SCHEMA_VERSION = "5"


class WriterLease:
    """A non-blocking cross-process lease for one SQLite writer manager."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        self.lock_path = f"{self.db_path}.writer.lock"
        Path(self.lock_path).parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.lock_path, "a+", encoding="utf-8")
        try:
            try:
                import fcntl

                fcntl.flock(
                    self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
                self._lock_kind = "fcntl"
            except ImportError:
                import msvcrt

                self._file.seek(0)
                if not self._file.read(1):
                    self._file.write(" ")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                self._lock_kind = "msvcrt"
        except (BlockingIOError, OSError) as exc:
            self._file.close()
            raise DatabaseOwnershipError(
                f"State database {self.db_path!r} already has an active "
                "writer manager."
            ) from exc
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f"pid={os.getpid()}\n")
        self._file.flush()

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if self._lock_kind == "fcntl":
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()


class DatabaseStore:
    """Owns one reusable SQLAlchemy engine for a state database."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._preflight_schema()
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False, "timeout": 5.0},
        )
        event.listen(self.engine, "connect", self._configure_connection)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )

    @staticmethod
    def _configure_connection(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    def _preflight_schema(self) -> None:
        """Rejects unsupported databases before SQLAlchemy can modify them."""
        if not os.path.exists(self.db_path) or os.path.getsize(self.db_path) == 0:
            return
        uri = f"file:{Path(self.db_path).as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            user_tables = {name for name in tables if name != "sqlite_sequence"}
            if not user_tables:
                return
            if "manager_config" not in user_tables:
                raise StateRestoreError(
                    "Existing SQLite database has no ATT schema version; "
                    "it was not modified."
                )
            row = connection.execute(
                "SELECT config_value FROM manager_config "
                "WHERE config_key='schema_version'"
            ).fetchone()
            version = row[0] if row else None
            if version != STATE_SCHEMA_VERSION:
                raise StateRestoreError(
                    f"Unsupported state schema version {version!r}; expected "
                    f"{STATE_SCHEMA_VERSION!r}. The database was not modified."
                )
        finally:
            connection.close()

    def close(self) -> None:
        self.engine.dispose()

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
            self._write_proposals(
                session, snapshot.get("proposals", {})
            )
            self._write_agreements(session, snapshot.get("agreements"))
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
    def _materialize(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Performs expensive deep JSON copying on the persistence worker."""
        result = dict(snapshot)
        configs = snapshot.get("configs")
        if configs is not None:
            result["configs"] = {
                key: (
                    value
                    if key in {"schema_version", "root_ai_id"}
                    else json.dumps(value)
                )
                for key, value in configs.items()
            }
        result["agents"] = [
            {
                **agent,
                "last_context": (
                    json.dumps(agent["last_context"])
                    if agent.get("last_context") is not None
                    else None
                ),
                "messages": json.loads(json.dumps(list(agent["messages"]))),
            }
            for agent in snapshot.get("agents", ())
        ]
        result["teams"] = [
            {
                **team,
                "communication_rules": json.dumps(
                    team["communication_rules"]
                ),
                "status_map": json.dumps(team["status_map"]),
            }
            for team in snapshot.get("teams", ())
        ]
        result["inboxes"] = {
            team_id: {
                **inbox,
                "messages": json.loads(
                    json.dumps(list(inbox["messages"]))
                ),
            }
            for team_id, inbox in snapshot.get("inboxes", {}).items()
        }
        result["proposals"] = json.loads(
            json.dumps(snapshot.get("proposals", {}))
        )
        result["permissions"] = json.loads(
            json.dumps(snapshot.get("permissions", {}))
        )
        result["links"] = json.loads(
            json.dumps(snapshot.get("links", {}))
        )
        return result

    def read(self) -> Dict[str, Any]:
        """Reads all persisted state into detached plain Python structures."""
        session = self.session_factory()
        try:
            config_map = {
                row.config_key: row.config_value
                for row in session.query(ManagerConfigModel).all()
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
                for proposal in session.query(TeamProposalModel).filter_by(
                    team_id=row.team_id
                ):
                    proposals.append(
                        {
                            "proposal_id": proposal.proposal_id,
                            "action": proposal.action,
                            "target": proposal.target,
                            "initiator_type": proposal.initiator_type,
                            "initiator_name": proposal.initiator_name,
                            "initiator_agent_id": proposal.initiator_agent_id,
                            "rationale": proposal.rationale,
                            "proposed_details": json.loads(
                                proposal.proposed_details or "{}"
                            ),
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
                        "creator_type": (
                            "agent" if row.creator_agent_id else "team"
                        ),
                        "creator_id": (
                            row.creator_agent_id or row.creator_team_id
                        ),
                        "communication_rules": row.communication_rules,
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
                    for file_row in session.query(DocLibFileModel).filter_by(
                        lib_id=row.lib_id
                    )
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
                permissions.setdefault(row.lib_id, {}).setdefault(row.path, {})[
                    row.team_id
                ] = row.permission

            links: Dict[str, Dict[str, Dict[str, str]]] = {}
            for row in session.query(DocLibLinkModel).all():
                links.setdefault(row.source_lib_id, {})[row.source_path] = {
                    "target_lib_id": row.target_lib_id,
                    "target_path": row.target_path,
                }

            agreements = [
                (row.sender_team_id, row.recipient_team_id)
                for row in session.query(BrokerAgreementModel).all()
            ]

            return {
                "configs": config_map,
                "agents": agents,
                "teams": teams,
                "libraries": libraries,
                "permissions": permissions,
                "links": links,
                "agreements": agreements,
            }
        finally:
            session.close()

    @staticmethod
    def _clear_all(session: Any) -> None:
        for model in (
            AgentMessageModel,
            TeamInboxModel,
            TeamProposalModel,
            BrokerAgreementModel,
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
            session.query(LibraryPermissionModel).filter_by(
                lib_id=lib_id
            ).delete(synchronize_session=False)
            session.query(DocLibFileModel).filter_by(
                lib_id=lib_id
            ).delete(synchronize_session=False)
            session.query(LibraryModel).filter_by(
                lib_id=lib_id
            ).delete(synchronize_session=False)
        for agent_id in snapshot.get("deleted_agents", ()):
            session.execute(
                delete(team_members).where(
                    team_members.c.agent_id == agent_id
                )
            )
            session.query(AgentMessageModel).filter_by(
                agent_id=agent_id
            ).delete(synchronize_session=False)
            session.query(AgentModel).filter_by(
                agent_id=agent_id
            ).delete(synchronize_session=False)

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
            session.query(AgentMessageModel).filter_by(
                agent_id=agent["agent_id"]
            ).delete(synchronize_session=False)
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
                        team["creator_id"]
                        if team["creator_type"] == "agent"
                        else None
                    ),
                    creator_team_id=(
                        team["creator_id"]
                        if team["creator_type"] == "team"
                        else None
                    ),
                    communication_rules=team["communication_rules"],
                    status_map=team["status_map"],
                    system_instructions=team["system_instructions"],
                )
            )
        session.flush()
        for team in teams:
            session.query(TeamModel).filter_by(
                team_id=team["team_id"]
            ).update(
                {"parent_team_id": team["parent_team_id"]},
                synchronize_session=False,
            )
        session.flush()
        for team in teams:
            session.execute(
                delete(team_members).where(
                    team_members.c.team_id == team["team_id"]
                )
            )
            for member_id in team["members"]:
                session.execute(
                    team_members.insert().values(
                        team_id=team["team_id"], agent_id=member_id
                    )
                )

    @staticmethod
    def _write_inboxes(
        session: Any, inboxes: Dict[str, Dict[str, Any]]
    ) -> None:
        for team_id, inbox in inboxes.items():
            session.query(TeamInboxModel).filter_by(
                team_id=team_id
            ).delete(synchronize_session=False)
            for index, message in enumerate(inbox["messages"]):
                session.add(
                    TeamInboxModel(
                        team_id=team_id,
                        sender=message.get("from", "Unknown"),
                        msg_type=message.get("type", "Unknown"),
                        payload=json.dumps(message),
                        created_at=(
                            inbox["message_timestamp"] + index * 0.001
                        ),
                    )
                )

    @staticmethod
    def _write_proposals(
        session: Any, proposals: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        for team_id, team_proposals in proposals.items():
            session.query(TeamProposalModel).filter_by(
                team_id=team_id
            ).delete(synchronize_session=False)
            for proposal in team_proposals:
                session.add(
                    TeamProposalModel(
                        proposal_id=proposal["proposal_id"],
                        team_id=team_id,
                        action=proposal.get("action"),
                        target=proposal.get("target"),
                        initiator_type=proposal.get("initiator_type"),
                        initiator_name=proposal.get("initiator_name"),
                        initiator_agent_id=proposal.get(
                            "initiator_agent_id"
                        ),
                        rationale=proposal.get("rationale"),
                        proposed_details=json.dumps(
                            proposal.get("proposed_details", {})
                        ),
                        votes=json.dumps(proposal.get("votes", {})),
                        status=proposal.get("status"),
                    )
                )

    @staticmethod
    def _write_agreements(
        session: Any, agreements: Optional[List[List[str]]]
    ) -> None:
        if agreements is None:
            return
        session.query(BrokerAgreementModel).delete(synchronize_session=False)
        for sender_id, recipient_id in agreements:
            session.add(
                BrokerAgreementModel(
                    sender_team_id=sender_id,
                    recipient_team_id=recipient_id,
                )
            )

    @staticmethod
    def _write_libraries(
        session: Any, libraries: Iterable[Dict[str, Any]]
    ) -> None:
        for library in libraries:
            session.merge(
                LibraryModel(
                    lib_id=library["lib_id"],
                    name=library["name"],
                    owner_team_id=library["owner_team_id"],
                    owner_agent_id=library.get("owner_agent_id"),
                    library_kind=library.get("library_kind", "team"),
                    lifecycle_state=library.get(
                        "lifecycle_state", "active"
                    ),
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
                session.query(DocLibFileModel).filter_by(
                    lib_id=lib_id, path=path
                ).delete(synchronize_session=False)
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
            session.query(DocLibLinkModel).filter_by(
                source_lib_id=source_lib_id
            ).delete(synchronize_session=False)
            for source_path, target in path_map.items():
                session.add(
                    DocLibLinkModel(
                        source_lib_id=source_lib_id,
                        source_path=source_path,
                        target_lib_id=target["target_lib_id"],
                        target_path=target["target_path"],
                    )
                )


class PersistenceCoordinator:
    """Runs one write and coalesces all later deltas into one pending write."""

    def __init__(self, db_path: Optional[str] = None):
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="att-state-writer"
        )
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
                    raise RuntimeError(
                        "Cannot queue deltas for different databases before flush."
                    )
                self._pending_snapshot = self._merge_snapshots(
                    self._pending_snapshot, snapshot
                )
            return self._pending_completion

    async def read(self, db_path: str) -> Dict[str, Any]:
        self.claim(db_path)
        await self.flush()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self._read, db_path
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
                *(
                    asyncio.shield(asyncio.wrap_future(future))
                    for future in futures
                ),
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
        self._active_task = self._executor.submit(
            self._write, db_path, snapshot
        )
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
                path = self._pending_path
                snapshot = self._pending_snapshot
                pending_completion = self._pending_completion
                self._pending_path = None
                self._pending_snapshot = None
                self._pending_completion = None
                self._start_locked(path, snapshot, pending_completion)

    @staticmethod
    def _merge_snapshots(
        earlier: Dict[str, Any], later: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Coalesces immutable deltas without losing later entity values."""
        if later.get("_capture_error") is not None:
            return later
        if earlier.get("_capture_error") is not None:
            return earlier
        if later.get("full"):
            return later
        merged = dict(earlier)
        merged["full"] = bool(earlier.get("full"))
        merged["state_version"] = later.get(
            "state_version", earlier.get("state_version")
        )
        if later.get("configs") is not None:
            merged["configs"] = later["configs"]
        if later.get("agreements") is not None:
            merged["agreements"] = later["agreements"]

        for key, identity in (
            ("agents", "agent_id"),
            ("teams", "team_id"),
            ("libraries", "lib_id"),
        ):
            records = {
                record[identity]: record
                for record in earlier.get(key, [])
            }
            records.update(
                {
                    record[identity]: record
                    for record in later.get(key, [])
                }
            )
            merged[key] = list(records.values())

        for key in ("inboxes", "proposals", "permissions", "links"):
            records = dict(earlier.get(key, {}))
            records.update(later.get(key, {}))
            merged[key] = records

        file_changes = {
            lib_id: dict(changes)
            for lib_id, changes in earlier.get("file_changes", {}).items()
        }
        for lib_id, changes in later.get("file_changes", {}).items():
            file_changes.setdefault(lib_id, {}).update(changes)
        merged["file_changes"] = file_changes
        merged["deleted_agents"] = list(
            set(earlier.get("deleted_agents", ()))
            | set(later.get("deleted_agents", ()))
        )
        merged["deleted_libraries"] = list(
            set(earlier.get("deleted_libraries", ()))
            | set(later.get("deleted_libraries", ()))
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
        for key in ("permissions", "links", "file_changes"):
            merged[key] = {
                lib_id: value
                for lib_id, value in merged.get(key, {}).items()
                if lib_id not in deleted_libraries
            }
        return merged
