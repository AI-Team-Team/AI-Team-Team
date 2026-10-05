"""Publish formal decisions through continuing Agents' personal inboxes."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from .communication import ApprovalPrincipal, CommunicationBallot


@dataclass
class DecisionOutcome:
    status: str
    reason: str
    ballots: List[CommunicationBallot] = field(default_factory=list)
    selected_value: Optional[str] = None
    round_id: Optional[str] = None


class TeamDecisionProvider:
    """Deliberates, publishes email rounds, and observes explicit tool choices."""

    def __init__(self, manager: Any):
        self.manager = manager

    @staticmethod
    def outcome(item) -> DecisionOutcome:
        if item is None:
            return DecisionOutcome("pending", "No eligible unchanged electorate is available.")
        status = item.status.lower() if item.status in {"APPROVED", "DENIED"} else "pending"
        ballots = []
        if item.choice_kind == "boolean" and item.principal.kind == "agent_team":
            ballots = [
                CommunicationBallot(
                    request_id=item.business_id,
                    principal=item.principal,
                    voter_agent_id=ballot.voter_agent_id,
                    approved=ballot.choice["approved"],
                    reason=ballot.choice["reason"],
                    created_at=ballot.created_at,
                )
                for ballot in item.ballots
            ]
        selected = None
        if item.choice_kind == "model" and item.status == "APPROVED":
            selected = next(
                alias
                for alias in item.candidates
                if sum(ballot.choice["model_alias"] == alias for ballot in item.ballots)
                > len(item.ballots) / 2
            )
        return DecisionOutcome(
            status,
            item.reason or "Personal voting emails are awaiting explicit choices.",
            ballots,
            selected,
            item.round_id,
        )

    async def decide_agent_boolean(
        self,
        principal: ApprovalPrincipal,
        prompt: str,
        *,
        request_id: str,
        business_kind: str = "communication",
    ) -> DecisionOutcome:
        if principal.kind != "agent":
            raise ValueError("Agent decision requires an agent principal.")
        item = await self.manager._governance.create_round(
            principal, business_kind, request_id, prompt
        )
        return self.outcome(item)

    async def ballot_team_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
        transcript: str,
        members: Sequence[Any],
        *,
        business_kind: str = "communication",
    ) -> DecisionOutcome:
        if principal.kind != "agent_team":
            raise ValueError("AgentTeam ballot requires an agent_team principal.")
        item = await self.manager._governance.create_round(
            principal, business_kind, request_id, prompt, transcript=transcript, members=members
        )
        return self.outcome(item)

    async def decide_team_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
        *,
        rounds: int = 1,
        business_kind: str = "communication",
    ) -> DecisionOutcome:
        team = self.manager.teams.get(principal.principal_id)
        if team is None:
            return DecisionOutcome("pending", "The approval AgentTeam is missing.")
        discussion, members = await self.manager._execute_team_discussion_with_members(
            team,
            prompt,
            rounds=rounds,
            require_complete=True,
        )
        return await self.ballot_team_boolean(
            principal,
            request_id,
            prompt,
            discussion.transcript,
            members,
            business_kind=business_kind,
        )

    async def decide_principal_boolean(
        self,
        principal: ApprovalPrincipal,
        request_id: str,
        prompt: str,
        *,
        business_kind: str = "migration",
    ) -> DecisionOutcome:
        if principal.kind == "agent":
            return await self.decide_agent_boolean(
                principal, prompt, request_id=request_id, business_kind=business_kind
            )
        return await self.decide_team_boolean(
            principal, request_id, prompt, business_kind=business_kind
        )

    async def _decide_model(
        self, principal: ApprovalPrincipal, prompt: str, candidates: Sequence[str]
    ) -> DecisionOutcome:
        candidates = list(candidates)
        if (
            not candidates
            or any(not isinstance(alias, str) or not alias.strip() for alias in candidates)
            or len(candidates) != len(set(candidates))
        ):
            raise ValueError("Model selection requires non-empty unique eligible aliases.")
        prompt += "\nEligible model aliases: " + json.dumps(candidates)
        # This bounded resource attempt does not survive an interrupted caller.
        request_id = f"FAILOVER-{uuid.uuid4().hex}"
        expires_at = time.time() + self.manager.config.parent_failover_timeout_seconds
        transcript = ""
        members = None
        if principal.kind == "agent_team":
            team = self.manager.teams.get(principal.principal_id)
            if team is None:
                return DecisionOutcome("pending", "The approval AgentTeam is missing.")
            discussion, members = await self.manager._execute_team_discussion_with_members(
                team,
                prompt,
                rounds=1,
                require_complete=True,
            )
            transcript = discussion.transcript
        try:
            if time.time() >= expires_at:
                return DecisionOutcome("pending", "The bounded failover attempt expired.")
            item = await self.manager._governance.create_round(
                principal,
                "failover",
                request_id,
                prompt,
                transcript=transcript,
                members=members,
                candidates=candidates,
                expires_at=expires_at,
            )
            if item is None:
                return self.outcome(None)
            waiter = self.manager._governance.waiters.setdefault(item.round_id, asyncio.Event())
            if item.status == "PENDING":
                await asyncio.wait_for(waiter.wait(), timeout=max(0, expires_at - time.time()))
            current = self.manager._governance.rounds[item.round_id]
            if not self.manager._governance.electorate_valid(current):
                return DecisionOutcome(
                    "pending", "Membership changed before the resource decision."
                )
            return self.outcome(current)
        finally:
            # Creation itself can be cancelled after the email transaction commits.
            # Resolve by execution identity, not just a returned local variable.
            current = self.manager._governance.latest("failover", request_id, principal)
            if current is not None and current.status == "PENDING":
                await asyncio.shield(
                    self.manager._governance.expire(
                        current.round_id,
                        "The bounded failover attempt ended without a complete decision.",
                    )
                )
            if current is not None:
                self.manager._governance.waiters.pop(current.round_id, None)

    async def decide_agent_model(
        self, principal: ApprovalPrincipal, prompt: str, candidates: Sequence[str]
    ) -> DecisionOutcome:
        if principal.kind != "agent":
            raise ValueError("Agent model selection requires an agent principal.")
        return await self._decide_model(principal, prompt, candidates)

    async def decide_team_model(
        self, principal: ApprovalPrincipal, prompt: str, candidates: Sequence[str]
    ) -> DecisionOutcome:
        if principal.kind != "agent_team":
            raise ValueError("AgentTeam model selection requires an agent_team principal.")
        return await self._decide_model(principal, prompt, candidates)
