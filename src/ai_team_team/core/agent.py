import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Any

if TYPE_CHECKING:
    from .manager import ATTManager
    from .team import AgentTeam

class Agent:
    """Represents an autonomous AI participant holding private conversation histories."""
    def __init__(
        self,
        name: str,
        role: str,
        llm_client: Optional[Any] = None,
        role_description: str = "",
        system_instructions: str = "",
        agent_id: Optional[str] = None,
    ):
        if agent_id is None:
            self._agent_id = str(uuid.uuid4())
        else:
            if not isinstance(agent_id, str):
                raise ValueError("agent_id must be a canonical UUID string.")
            try:
                parsed_agent_id = uuid.UUID(agent_id)
            except (ValueError, AttributeError) as exc:
                raise ValueError(
                    "agent_id must be a canonical UUID string."
                ) from exc
            if str(parsed_agent_id) != agent_id:
                raise ValueError("agent_id must be a canonical UUID string.")
            self._agent_id = agent_id
        self.name = name
        self.role = role
        self.llm_client = llm_client
        self.role_description = role_description
        self.system_instructions = system_instructions
        self.messages: List[Dict[str, str]] = []
        self.message_history: List[Dict[str, Any]] = []
        self._history_seen_ids: set[int] = set()
        self.last_context: Optional[Dict[str, Any]] = None
        self._lock: Optional[asyncio.Lock] = None
        self._lifecycle_lock: Optional[asyncio.Lock] = None
        self.lifecycle_state = "active"
        self._private_doc_library_id: Optional[str] = None
        self._model_alias: Optional[str] = None

    @property
    def agent_id(self) -> str:
        """Returns the immutable persistent identity of this agent."""
        return self._agent_id

    @property
    def private_doc_library_id(self) -> Optional[str]:
        """Returns the manager-assigned private library identifier."""
        return self._private_doc_library_id

    @property
    def lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def lifecycle_lock(self) -> asyncio.Lock:
        """Serializes retirement and reactivation for this identity."""
        if self._lifecycle_lock is None:
            self._lifecycle_lock = asyncio.Lock()
        return self._lifecycle_lock

    @asynccontextmanager
    async def invocation_guard(self):
        """Atomically starts one serialized invocation against lifecycle changes."""
        async with self.lifecycle_lock:
            if self.lifecycle_state != "active":
                raise RuntimeError("Inactive agents cannot execute model calls.")
            await self.lock.acquire()
        try:
            yield
        finally:
            self.lock.release()

    def sync_message_history(self) -> None:
        """Captures messages inserted directly through the compatibility list."""
        for message in self.messages:
            identity = id(message)
            if identity not in self._history_seen_ids:
                self.message_history.append(message)
                self._history_seen_ids.add(identity)

    def append_message(self, message: Dict[str, Any]) -> None:
        """Appends to the model window and the complete persistent history."""
        self.sync_message_history()
        self.messages.append(message)
        self.message_history.append(message)
        self._history_seen_ids.add(id(message))

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_members: Optional[List["Agent"]] = None,
        existing_member_ids: Optional[List[str]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None
    ) -> 'AgentTeam':
        """Allows this agent to launch a dynamic sub-team (Level $N$)."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=existing_members,
            existing_member_ids=existing_member_ids,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        parent = manager.get_agent_team(self)
        if parent is not None:
            child.chapter_num = parent.chapter_num
        return child
