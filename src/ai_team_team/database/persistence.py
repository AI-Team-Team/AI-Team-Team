import asyncio
import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from ai_team_team.core.exceptions import StateRestoreError
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


STATE_SCHEMA_VERSION = "3"


class DatabaseStore:
    """Owns one reusable SQLAlchemy engine for a state database."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )

    def close(self) -> None:
        self.engine.dispose()

    def write(self, snapshot: Dict[str, Any]) -> None:
        """Writes a full snapshot or an incremental immutable delta."""
        session = self.session_factory()
        try:
            if snapshot["full"]:
                self._clear_all(session)

            self._write_configs(session, snapshot.get("configs"))
            self._write_agents(session, snapshot.get("agents", []))
            self._write_teams(session, snapshot.get("teams", []))
            self._write_inboxes(session, snapshot.get("inboxes", {}))
            self._write_proposals(
                session, snapshot.get("proposals", {})
            )
            self._write_agreements(session, snapshot.get("agreements"))
            self._write_libraries(session, snapshot.get("libraries", []))
            self._write_permissions(session, snapshot.get("permissions", {}))
            self._write_file_changes(session, snapshot.get("file_changes", {}))
            self._write_links(session, snapshot.get("links"))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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
                    .filter_by(agent_name=row.name)
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
                        }
                    )
                agents.append(
                    {
                        "name": row.name,
                        "role": row.role,
                        "role_description": row.role_description,
                        "system_instructions": row.system_instructions,
                        "model_alias": row.model_alias,
                        "last_context": row.last_context,
                        "messages": messages,
                    }
                )

            teams = []
            for row in session.query(TeamModel).all():
                member_names = [
                    name
                    for (name,) in session.query(team_members.c.agent_name)
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
                        "creator_type": row.creator_type,
                        "creator_id": row.creator_id,
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
        session.query(TeamModel).delete(synchronize_session=False)
        session.query(AgentModel).delete(synchronize_session=False)
        session.query(LibraryModel).delete(synchronize_session=False)
        session.query(ManagerConfigModel).delete(synchronize_session=False)

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
                    name=agent["name"],
                    role=agent["role"],
                    role_description=agent["role_description"],
                    system_instructions=agent["system_instructions"],
                    model_alias=agent["model_alias"],
                    last_context=agent["last_context"],
                )
            )
            session.query(AgentMessageModel).filter_by(
                agent_name=agent["name"]
            ).delete(synchronize_session=False)
            for index, message in enumerate(agent["messages"]):
                session.add(
                    AgentMessageModel(
                        agent_name=agent["name"],
                        role=message.get("role", "user"),
                        content=message.get("content"),
                        tool_calls=message.get("tool_calls"),
                        tool_call_id=message.get("tool_call_id"),
                        name=message.get("name"),
                        created_at=agent["message_timestamp"] + index * 0.001,
                    )
                )

    @staticmethod
    def _write_teams(session: Any, teams: Iterable[Dict[str, Any]]) -> None:
        for team in teams:
            session.merge(
                TeamModel(
                    team_id=team["team_id"],
                    preset_name=team["preset_name"],
                    team_purpose=team["team_purpose"],
                    team_progress=team["team_progress"],
                    depth=team["depth"],
                    chapter_num=team["chapter_num"],
                    parent_team_id=team["parent_team_id"],
                    migration_count=team["migration_count"],
                    creator_type=team["creator_type"],
                    creator_id=team["creator_id"],
                    communication_rules=team["communication_rules"],
                    status_map=team["status_map"],
                    system_instructions=team["system_instructions"],
                )
            )
            session.execute(
                delete(team_members).where(
                    team_members.c.team_id == team["team_id"]
                )
            )
            for member_name in team["members"]:
                session.execute(
                    team_members.insert().values(
                        team_id=team["team_id"], agent_name=member_name
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
    """Serializes all database work through one reusable worker thread."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="att-state-writer"
        )
        self._stores: Dict[str, DatabaseStore] = {}
        self._futures: List[Future[Any]] = []
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, db_path: str, snapshot: Dict[str, Any]) -> Future[Any]:
        if self._closed:
            raise RuntimeError("Persistence coordinator is closed.")
        future = self._executor.submit(self._write, db_path, snapshot)
        with self._lock:
            self._futures.append(future)
        return future

    async def read(self, db_path: str) -> Dict[str, Any]:
        await self.flush()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self._read, db_path
        )

    async def flush(self) -> None:
        while True:
            with self._lock:
                futures = self._futures
                self._futures = []
            if not futures:
                return
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in futures)
            )

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
        self._store(db_path).write(snapshot)

    def _read(self, db_path: str) -> Dict[str, Any]:
        return self._store(db_path).read()
