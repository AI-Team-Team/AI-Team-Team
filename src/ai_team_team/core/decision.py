"""Create explicit personal-mail cases without invoking or choosing a person."""

from dataclasses import dataclass, field
from typing import Any, Optional

from .communication import ApprovalPrincipal, CommunicationBallot


@dataclass
class DecisionOutcome:
    status: str
    reason: str
    ballots: list[CommunicationBallot] = field(default_factory=list)
    selected_value: Optional[str] = None
    case_id: Optional[str] = None


class TeamDecisionProvider:
    """Authority comes only from immutable ballots, never an ordinary answer."""

    def __init__(self, manager: Any):
        self.manager = manager

    @staticmethod
    def outcome(item) -> DecisionOutcome:
        if item is None:
            return DecisionOutcome("pending", "No eligible unchanged electorate is available.")
        status = item.status.lower() if item.status in {"APPROVED", "DENIED"} else "pending"
        ballots = []
        if item.choice_kind == "boolean" and item.principal.kind == "agent_team":
            ballots = [CommunicationBallot(request_id=item.business_id, principal=item.principal,
                voter_agent_id=ballot.voter_agent_id, approved=ballot.choice["approved"],
                reason=ballot.choice["reason"], created_at=ballot.created_at) for ballot in item.ballots]
        selected = None
        if item.choice_kind == "model" and item.status == "APPROVED":
            selected = next(alias for alias in item.candidates if sum(
                ballot.choice["model_alias"] == alias for ballot in item.ballots) > len(item.ballots) / 2)
        return DecisionOutcome(status, item.reason or "Awaiting explicit personal choices.",
            ballots, selected, item.case_id)

    async def decide_principal_boolean(self, principal: ApprovalPrincipal, request_id: str,
            prompt: str, *, business_kind: str = "migration") -> DecisionOutcome:
        item = await self.manager._governance.create_case(principal, business_kind, request_id, prompt)
        return self.outcome(item)

    async def request_model_choice(self, principal: ApprovalPrincipal, request_id: str,
            prompt: str, candidates: list[str], *, expires_at: float) -> DecisionOutcome:
        if not candidates or len(set(candidates)) != len(candidates):
            raise ValueError("Model selection requires unique eligible aliases.")
        item = await self.manager._governance.create_case(principal, "failover", request_id,
            prompt, candidates=candidates, expires_at=expires_at)
        return self.outcome(item)
