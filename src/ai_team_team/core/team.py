import uuid
import asyncio
import logging
import threading
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Any, Union
from ai_team_team.tool import Tool
from ai_team_team.doc_library import DocumentLibrary
from .agent import Agent

if TYPE_CHECKING:
    from .formation import TeamFormationRequest
    from .manager import ATTManager

class AgentTeam:
    """An organizational team with explicit membership and parent relations."""
    def __init__(
        self,
        creator: Any,
        preset_name: str,
        team_purpose: str = "Unspecified team purpose",
        *,
        team_kind: str = "ordinary",
    ):
        if team_kind not in {"ordinary", "supervisory"}:
            raise ValueError("team_kind must be ordinary or supervisory.")
        self.team_id = f"AT-{uuid.uuid4().hex[:6]}"
        self.team_kind = team_kind
        self.creator = creator
        self.preset_name = preset_name
        self.team_purpose = team_purpose
        self.team_progress = "Not started"
        self.proposals: Dict[str, Dict[str, Any]] = {}
        self.chapter_num: Optional[int] = None
        self.status_map: Dict[str, str] = {}
        self.members: List[Agent] = []
        
        self.child_teams: List['AgentTeam'] = []
        self.logger = logging.getLogger(f"AgentTeam:{self.team_id}")
        self.message_inbox: List[Dict[str, Any]] = []
        self.tools: Dict[str, Tool] = {}
        self._parent_team: Optional['AgentTeam'] = None
        self._position_revision = 1
        self.doc_library: Optional[DocumentLibrary] = None
        self._cached_depth: Optional[int] = None
        self._state_lock: Optional[asyncio.Lock] = None
        self._status_lock = threading.RLock()
        self._inbox_lock = threading.RLock()

    @property
    def state_lock(self):
        import asyncio
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    @property
    def parent_team(self) -> Optional['AgentTeam']:
        return self._parent_team

    @property
    def organizational_parent(self):
        from .communication import ApprovalPrincipal

        if self._parent_team is not None:
            return ApprovalPrincipal(kind="agent_team", principal_id=self._parent_team.team_id)
        owner = getattr(self, "_parent_agent_id", None)
        return ApprovalPrincipal(kind="agent", principal_id=owner) if owner else None

    @property
    def is_independent(self) -> bool:
        return self.organizational_parent is None

    @property
    def depth(self) -> int:
        if self._cached_depth is not None:
            return self._cached_depth
        
        d = 1
        curr = self.parent_team
        while curr is not None:
            d += 1
            curr = curr.parent_team
            
        self._cached_depth = d
        return d

    def add_child_team(self, child: 'AgentTeam'):
        if child not in self.child_teams:
            self.child_teams.append(child)

    def invalidate_depth_cache(self, recursive: bool = True) -> None:
        """Clears cached depth for this team and optionally all descendants."""
        self._cached_depth = None
        if recursive:
            for child in self.child_teams:
                child.invalidate_depth_cache(recursive=True)

    def set_status(self, agent_name: str, status: str) -> None:
        """Updates display-only status under a lightweight synchronous lock."""
        with self._status_lock:
            self.status_map[agent_name] = status

    def status_snapshot(self) -> Dict[str, str]:
        """Returns a consistent copy of display-only status."""
        with self._status_lock:
            return dict(self.status_map)

    @property
    def inbox_lock(self) -> threading.RLock:
        """Returns the short-lived lock protecting inbox handoff."""
        return self._inbox_lock

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_members: Optional[List[Agent]] = None,
        existing_member_ids: Optional[List[str]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None,
        initiating_agent: Optional[Agent] = None,
        initiator_joins: bool = False,
        unanimous_acceptance_action: str = "require_confirmation",
        late_join_policy: str = "disabled",
        task: Optional[str] = None,
    ) -> "AgentTeam | TeamFormationRequest":
        """Allows any active team to recursively launch their own child AT."""
        child = manager.create_agent_team(
            creator=self,
            parent=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=existing_members,
            existing_member_ids=existing_member_ids,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs,
            initiating_agent=initiating_agent,
            initiator_joins=initiator_joins,
            unanimous_acceptance_action=unanimous_acceptance_action,
            late_join_policy=late_join_policy,
            task=task,
        )
        if hasattr(child, "chapter_num"):
            child.chapter_num = self.chapter_num
        return child


    def receive_message(self, message: Dict[str, Any]) -> None:
        """Retain an addressed organizational item without starting a discussion."""
        with self._inbox_lock:
            self.message_inbox.append(dict(message))
        manager = getattr(self, "manager", None)
        if manager is not None:
            manager._auto_save(inboxes={self.team_id})
