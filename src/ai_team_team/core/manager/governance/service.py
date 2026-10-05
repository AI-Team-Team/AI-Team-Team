"""State ownership and restoration for durable governance rounds."""

import asyncio
import threading
import time
from typing import Any

from ...governance import GovernanceRound
from .rounds import GovernanceRoundMixin
from .scheduling import GovernanceSchedulingMixin
from .submissions import GovernanceSubmissionMixin


class GovernanceService(GovernanceRoundMixin, GovernanceSubmissionMixin, GovernanceSchedulingMixin):
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.rounds: dict[str, GovernanceRound] = {}
        self.lock = asyncio.Lock()
        self.state_lock = threading.RLock()
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.waiters: dict[str, asyncio.Event] = {}

    def snapshot(self) -> list[dict[str, Any]]:
        with self.state_lock:
            return [item.model_dump(mode="json") for item in self.rounds.values()]

    def restore(self, rows, *, interrupted: bool = True) -> None:
        self.rounds = {
            item.round_id: item
            for item in (GovernanceRound.model_validate(row, strict=False) for row in rows)
        }
        self.waiters.clear()
        if interrupted:
            for item in self.rounds.values():
                if item.business_kind == "failover" and item.status == "PENDING":
                    item.status = "EXPIRED"
                    item.reason = "The original model invocation ended when its process stopped."
                    item.resolved_at = time.time()

    def latest(self, business_kind: str, business_id: str, principal: Any):
        with self.state_lock:
            candidates = [
                item
                for item in self.rounds.values()
                if item.business_kind == business_kind
                and item.business_id == business_id
                and item.principal == principal
            ]
            return max(candidates, key=lambda item: item.round_number, default=None)

    def is_outstanding(self, agent_id: str, round_id: Any) -> bool:
        item = self.rounds.get(round_id) if isinstance(round_id, str) else None
        return bool(
            item
            and item.status == "PENDING"
            and self.business_pending(item)
            and agent_id in item.voter_agent_ids
            and not any(ballot.voter_agent_id == agent_id for ballot in item.ballots)
        )

    def inspect(self, actor, round_id):
        item = self.rounds.get(round_id)
        if item is None or actor.agent_id not in item.voter_agent_ids:
            raise PermissionError("The governance round is not addressed to this Agent.")
        result = item.model_dump(mode="json")
        result["choice_schema"] = self.choice_model(item).model_json_schema()
        result["instructions"] = (
            "Opening this email does not vote or mark it read. You may independently submit a choice with submit_governance_choice, or leave it unanswered. Only an explicit valid submission counts."
        )
        return result

    @staticmethod
    def choice_model(item):
        from ...governance import BooleanGovernanceChoice, ModelGovernanceChoice

        return BooleanGovernanceChoice if item.choice_kind == "boolean" else ModelGovernanceChoice

    async def expire(self, round_id: str, reason: str) -> None:
        async with self.lock:
            item = self.rounds[round_id]
            if item.status != "PENDING":
                return
            previous = item.model_copy(deep=True)
            item.status = "EXPIRED"
            item.reason = reason
            item.resolved_at = time.time()
            dirty = self.manager._new_dirty_state()
            dirty["governance_rounds"].add(round_id)
            try:
                await self.manager._commit_dirty_state(dirty)
            except Exception:
                self.rounds[round_id] = previous
                raise
            if waiter := self.waiters.get(round_id):
                waiter.set()
