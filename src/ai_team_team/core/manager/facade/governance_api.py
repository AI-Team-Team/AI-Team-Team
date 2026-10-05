"""Personal email and explicit governance choices for continuing Agents."""

import uuid
from typing import Any, Optional

from ...agent import Agent
from ...exceptions import AgentTurnIncompleteError, LLMGenerationError, TokenLimitExceededError
from ...governance import GovernanceSubmissionResult
from ...response import AgentTurnResult, AgentTurnStatus
from ...team import AgentTeam


class GovernanceAPI:
    def open_agent_mail(self, message_id: str, *, actor: Agent) -> dict[str, Any]:
        return self._inbox.open(actor, message_id)

    async def submit_governance_choice(
        self, round_id: str, choice: dict[str, Any], *, actor: Agent
    ) -> GovernanceSubmissionResult:
        return await self._governance.submit(actor, round_id, choice)

    def list_governance_requests(
        self, *, actor: Agent, pending_only: bool = True
    ) -> list[dict[str, Any]]:
        if self._agents_by_id.get(actor.agent_id) is not actor or actor.lifecycle_state != "active":
            raise PermissionError("Governance requests require an active registered Agent.")
        return [
            self._governance.inspect(actor, item.round_id)
            for item in self._governance.rounds.values()
            if actor.agent_id in item.voter_agent_ids
            and (not pending_only or self._governance.is_outstanding(actor.agent_id, item.round_id))
        ]

    async def execute_agent_interaction(
        self, agent: Agent, prompt: str, *, team: Optional[AgentTeam] = None
    ) -> AgentTurnResult:
        """Runs an ordinary serialized personal turn, never a standalone ballot prompt."""
        if team is not None:
            if self.teams.get(team.team_id) is not team or agent not in team.members:
                raise PermissionError("The interaction's AgentTeam must contain this Agent.")
            return await team.execute_reasoning_step_detailed(
                agent,
                prompt,
                team.system_instructions,
                max_steps=self.config.react_max_steps,
                manager=self,
            )
        from ...strategies import NativeReasoningStrategy, TextReactReasoningStrategy

        async with self.agent_invocation(agent):
            turn_id = f"TURN-{uuid.uuid4().hex}"
            turn_token = self._active_agent_turn_id.set(turn_id)
            team_token = self._active_team.set(None)
            discussion_token = self._active_discussion_id.set(None)
            round_token = self._active_round_number.set(None)
            self._memory.start_turn(agent, None, turn_id)
            try:
                mode = self.config.tool_calling_mode
                native = (
                    mode == "native"
                    or mode == "auto"
                    and self.probe_native_tool_capability(agent.llm_client, agent=agent)
                )
                strategy = NativeReasoningStrategy() if native else TextReactReasoningStrategy()
                try:
                    if agent.llm_client is None:
                        raise LLMGenerationError("Agent has no configured model client.")
                    result = await strategy.execute(
                        team=None,
                        agent=agent,
                        prompt=prompt,
                        system_instruction="",
                        max_steps=self.config.react_max_steps,
                        manager=self,
                    )
                except (LLMGenerationError, TokenLimitExceededError) as exc:
                    result = AgentTurnResult(
                        agent_id=agent.agent_id,
                        turn_id=turn_id,
                        status=AgentTurnStatus.INCOMPLETE,
                        error_kind="token_limit_exhausted"
                        if isinstance(exc, TokenLimitExceededError)
                        else "llm_generation_failed",
                        reason=str(exc),
                    )
                    if self.config.turn_failure_policy.llm == "abort":
                        raise AgentTurnIncompleteError(result) from exc
                else:
                    if (
                        result.status is AgentTurnStatus.INCOMPLETE
                        and self.config.turn_failure_policy.tool == "abort"
                    ):
                        raise AgentTurnIncompleteError(result)
                await self._memory.finalize_turn(agent, None, result)
                return result
            except AgentTurnIncompleteError as exc:
                await self._memory.finalize_turn(agent, None, exc.result)
                raise
            except BaseException as exc:
                self._memory.cancel_turn(agent, None, turn_id, type(exc).__name__)
                raise
            finally:
                self._active_round_number.reset(round_token)
                self._active_discussion_id.reset(discussion_token)
                self._active_team.reset(team_token)
                self._active_agent_turn_id.reset(turn_token)
