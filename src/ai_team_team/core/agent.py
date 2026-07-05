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
        self.last_context: Optional[Dict[str, Any]] = None
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self):
        import asyncio
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

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
        for team in manager.teams.values():
            if self in team.members:
                child.chapter_num = team.chapter_num
                break
        return child
