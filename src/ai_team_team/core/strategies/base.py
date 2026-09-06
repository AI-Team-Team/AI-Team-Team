"""Abstract reasoning-strategy contract."""

import abc
from typing import Any

from ai_team_team.core.agent import Agent
from ai_team_team.core.response import AgentTurnResult


class BaseReasoningStrategy(metaclass=abc.ABCMeta):
    """Abstract base class representing a reasoning strategy for an agent turn."""

    @abc.abstractmethod
    async def execute(
        self,
        team: Any,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int,
        manager: Any,
    ) -> AgentTurnResult:
        pass
