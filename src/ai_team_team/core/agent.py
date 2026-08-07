from typing import List, Dict, Optional, Tuple, Any

class Agent:
    """Represents an autonomous AI participant holding private conversation histories."""
    def __init__(self, name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = ""):
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

    @property
    def lock(self):
        import asyncio
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

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
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        parent = manager.get_agent_team(self)
        if parent is not None:
            child.chapter_num = parent.chapter_num
        return child
