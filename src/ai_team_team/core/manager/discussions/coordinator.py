"""Serialized AgentTeam discussion entry points."""

import uuid
from typing import TYPE_CHECKING, Any, List, Tuple

from ...agent import Agent
from ...team import AgentTeam

if TYPE_CHECKING:
    from ..facade import ATTManager
    from ...response import DiscussionResult


from .session import DiscussionSessionMixin


class DiscussionCoordinator(DiscussionSessionMixin):
    """Owns ordinary, governance, and emergency discussion sessions."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    async def execute_team_discussion(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> str:
        """Queues one discussion behind any active session for the same team."""
        result = await self.manager.execute_team_discussion_detailed(
            team,
            prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
        return result.transcript

    async def execute_team_discussion_detailed(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> "DiscussionResult":
        """Runs one serialized discussion and returns all structured turns."""
        result, _ = await self.manager._execute_team_discussion_with_members(
            team,
            prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
        return result

    async def _execute_team_discussion_with_members(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
        require_complete: bool = False,
    ) -> Tuple[Any, List[Agent]]:
        """Runs one serialized session and captures membership after locking."""
        if self.manager._closing:
            raise RuntimeError("ATTManager is closing and rejects new discussions.")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            raise ValueError("rounds must be a positive integer.")
        async with team.discussion_lock:
            async with self.manager._runtime_gate:
                if self.manager._closing:
                    raise RuntimeError("ATTManager is closing and rejects new discussions.")
                is_runtime_audit = bool(skip_audit and getattr(team, "_runtime_only", False))
                if self.manager.teams.get(team.team_id) is not team and not is_runtime_audit:
                    raise ValueError("The discussion team is not registered.")
                team.is_running = True
                member_snapshot = list(team.members)
            try:
                session_kwargs = {
                    "rounds": rounds,
                    "skip_audit": skip_audit,
                }
                if require_complete:
                    session_kwargs["require_complete"] = True
                result = await self.manager._execute_team_discussion_session(
                    team, prompt, **session_kwargs
                )
                if isinstance(result, str):
                    from ...response import (
                        AuditResult,
                        AuditStatus,
                        DiscussionResult,
                        DiscussionStatus,
                    )

                    result = DiscussionResult(
                        team_id=team.team_id,
                        discussion_id=(
                            self.manager._active_discussion_id.get() or f"DISC-{uuid.uuid4().hex}"
                        ),
                        status=DiscussionStatus.COMPLETED,
                        transcript=result,
                        rounds=[],
                        audit=AuditResult(
                            status=AuditStatus.HEALTHY,
                            reason="Compatibility session result.",
                        ),
                    )
                return result, member_snapshot
            finally:
                team.is_running = False
