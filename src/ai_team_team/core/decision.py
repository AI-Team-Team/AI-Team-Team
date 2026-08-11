"""Autonomous AgentTeam and Agent governance decisions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from .communication import ApprovalPrincipal, CommunicationBallot
from .utils import generate_with_retry


class StrictBooleanDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    approved: StrictBool
    reason: str = ""


class StrictModelDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    model_alias: str
    reason: str = ""


@dataclass
class DecisionOutcome:
    status: str
    reason: str
    ballots: List[CommunicationBallot] = field(default_factory=list)
    selected_value: Optional[str] = None


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    raise ValueError("The governance client returned no text response.")


def _clean_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


class TeamDecisionProvider:
    """Forms decisions only for explicitly configured principals."""

    def __init__(self, manager: Any):
        self.manager = manager

    async def _generate(self, agent: Any, prompt: str, system: str) -> str:
        if agent.lifecycle_state != "active" or agent.llm_client is None:
            raise RuntimeError(f"Approval Agent {agent.agent_id!r} is unavailable.")
        async with self.manager.agent_invocation(agent):
            response = await generate_with_retry(
                llm_client=agent.llm_client,
                prompt=prompt,
                system_instruction=system,
                temperature=0.1,
                require_json=True,
                retries=self.manager.config.llm_max_retries,
                backoff_factor=self.manager.config.llm_retry_backoff_factor,
                manager=self.manager,
            )
        return _response_text(response)

    async def decide_agent_boolean(
        self, principal: ApprovalPrincipal, prompt: str
    ) -> DecisionOutcome:
        if principal.kind != "agent":
            raise ValueError("Agent decision requires an agent principal.")
        agent = self.manager._agents_by_id.get(principal.principal_id)
        if agent is None:
            return DecisionOutcome("pending", "The approval Agent is missing.")
        try:
            raw = await self._generate(
                agent,
                prompt
                + "\n\nReturn exactly JSON: "
                '{"approved": true | false, "reason": "..."}',
                "You are an explicitly configured ATT governance principal. "
                "Decide only for your own authority and return strict JSON.",
            )
            decision = StrictBooleanDecision.model_validate_json(
                _clean_json(raw), strict=True
            )
        except asyncio.CancelledError:
            raise
        except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
            return DecisionOutcome(
                "pending", f"Agent governance decision failed: {exc}"
            )
        return DecisionOutcome(
            "approved" if decision.approved else "denied",
            decision.reason,
        )

    async def ballot_team_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
        transcript: str,
        members: Sequence[Any],
    ) -> DecisionOutcome:
        if principal.kind != "agent_team":
            raise ValueError("AgentTeam ballot requires an agent_team principal.")
        team = self.manager.teams.get(principal.principal_id)
        if team is None or not members:
            return DecisionOutcome(
                "pending", "The approval AgentTeam has no active members."
            )

        async def vote(agent: Any) -> Any:
            ballot_prompt = (
                f"Governance request:\n{prompt}\n\n"
                f"AgentTeam discussion transcript:\n{transcript}\n\n"
                "Cast your own final ballot. Return exactly JSON: "
                '{"approved": true | false, "reason": "..."}'
            )
            raw = await self._generate(
                agent,
                ballot_prompt,
                "You are voting as one member of an autonomous AgentTeam. "
                "Your ballot is one vote, not team authority. Return strict JSON.",
            )
            return StrictBooleanDecision.model_validate_json(
                _clean_json(raw), strict=True
            )

        results = await asyncio.gather(
            *(vote(agent) for agent in members), return_exceptions=True
        )
        if any(isinstance(result, asyncio.CancelledError) for result in results):
            raise asyncio.CancelledError
        if list(team.members) != list(members):
            return DecisionOutcome(
                "pending", "AgentTeam membership changed during the decision."
            )
        if any(isinstance(result, BaseException) for result in results):
            errors = [
                str(result)
                for result in results
                if isinstance(result, BaseException)
            ]
            return DecisionOutcome(
                "pending",
                "Not every AgentTeam member produced a valid ballot: "
                + "; ".join(errors),
            )

        ballots = [
            CommunicationBallot(
                request_id=request_id,
                principal=principal,
                voter_agent_id=agent.agent_id,
                approved=result.approved,
                reason=result.reason,
            )
            for agent, result in zip(members, results)
        ]
        approvals = sum(ballot.approved for ballot in ballots)
        denials = len(ballots) - approvals
        if approvals > len(ballots) / 2:
            return DecisionOutcome(
                "approved",
                f"AgentTeam approved by {approvals}/{len(ballots)} ballots.",
                ballots,
            )
        if denials > len(ballots) / 2:
            return DecisionOutcome(
                "denied",
                f"AgentTeam denied by {denials}/{len(ballots)} ballots.",
                ballots,
            )
        return DecisionOutcome(
            "pending", "AgentTeam ballot was tied.", ballots
        )

    async def decide_team_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
        *,
        rounds: int = 1,
    ) -> DecisionOutcome:
        team = self.manager.teams.get(principal.principal_id)
        if team is None:
            return DecisionOutcome("pending", "The approval AgentTeam is missing.")
        try:
            transcript, members = (
                await self.manager._execute_team_discussion_with_members(
                    team,
                    prompt,
                    rounds=rounds,
                    require_complete=True,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return DecisionOutcome(
                "pending", f"AgentTeam governance discussion failed: {exc}"
            )
        if not members:
            return DecisionOutcome(
                "pending", "The approval AgentTeam has no active members."
            )
        return await self.ballot_team_boolean(
            principal, request_id, prompt, transcript, members
        )

    async def decide_principal_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
    ) -> DecisionOutcome:
        if principal.kind == "agent":
            return await self.decide_agent_boolean(principal, prompt)
        return await self.decide_team_boolean(
            principal, request_id, prompt
        )

    async def decide_agent_model(
        self,
        principal: ApprovalPrincipal,
        prompt: str,
        candidates: Sequence[str],
    ) -> DecisionOutcome:
        if principal.kind != "agent":
            raise ValueError("Agent model selection requires an agent principal.")
        agent = self.manager._agents_by_id.get(principal.principal_id)
        if agent is None:
            return DecisionOutcome("pending", "The approval Agent is missing.")
        try:
            raw = await self._generate(
                agent,
                prompt
                + "\n\nAllowed model aliases: "
                + json.dumps(list(candidates))
                + '\nReturn exactly JSON: {"model_alias": "...", "reason": "..."}',
                "You are an explicitly configured ATT resource governance principal.",
            )
            decision = StrictModelDecision.model_validate_json(
                _clean_json(raw), strict=True
            )
            if decision.model_alias not in candidates:
                raise ValueError("The selected model alias is not a candidate.")
        except asyncio.CancelledError:
            raise
        except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
            return DecisionOutcome(
                "pending", f"Agent model selection failed: {exc}"
            )
        return DecisionOutcome(
            "approved", decision.reason, selected_value=decision.model_alias
        )

    async def decide_team_model(
        self,
        principal: ApprovalPrincipal,
        prompt: str,
        candidates: Sequence[str],
    ) -> DecisionOutcome:
        if principal.kind != "agent_team":
            raise ValueError("AgentTeam model selection requires an agent_team principal.")
        team = self.manager.teams.get(principal.principal_id)
        if team is None:
            return DecisionOutcome(
                "pending", "The approval AgentTeam has no active members."
            )
        try:
            transcript, members = (
                await self.manager._execute_team_discussion_with_members(
                    team,
                    prompt
                    + "\n\nDiscuss which model alias should be selected from: "
                    + json.dumps(list(candidates)),
                    rounds=1,
                    require_complete=True,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return DecisionOutcome(
                "pending", f"AgentTeam model-selection discussion failed: {exc}"
            )
        if not members:
            return DecisionOutcome(
                "pending", "The approval AgentTeam has no active members."
            )

        async def vote(agent: Any) -> Any:
            raw = await self._generate(
                agent,
                prompt
                + "\n\nDiscussion transcript:\n"
                + transcript
                + "\n\nAllowed aliases: "
                + json.dumps(list(candidates))
                + '\nReturn exactly JSON: {"model_alias": "...", "reason": "..."}',
                "Vote independently as one member of the AgentTeam. Return strict JSON.",
            )
            decision = StrictModelDecision.model_validate_json(
                _clean_json(raw), strict=True
            )
            if decision.model_alias not in candidates:
                raise ValueError("The selected model alias is not a candidate.")
            return decision

        results = await asyncio.gather(
            *(vote(agent) for agent in members), return_exceptions=True
        )
        if any(isinstance(result, asyncio.CancelledError) for result in results):
            raise asyncio.CancelledError
        if list(team.members) != members or any(
            isinstance(result, BaseException) for result in results
        ):
            return DecisionOutcome(
                "pending",
                "Not every AgentTeam member produced a valid model-selection ballot.",
            )
        counts = {
            candidate: sum(
                result.model_alias == candidate for result in results
            )
            for candidate in candidates
        }
        winners = [
            candidate
            for candidate, count in counts.items()
            if count > len(members) / 2
        ]
        if len(winners) != 1:
            return DecisionOutcome(
                "pending", "No model alias received a strict majority."
            )
        return DecisionOutcome(
            "approved",
            f"AgentTeam selected {winners[0]!r} by strict majority.",
            selected_value=winners[0],
        )
