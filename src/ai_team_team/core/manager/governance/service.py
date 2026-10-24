"""State ownership and restoration for durable governance cases."""

import asyncio
import contextvars
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from ...governance import GovernanceCase
from .cases import GovernanceCaseMixin
from .scheduling import GovernanceSchedulingMixin
from .submissions import GovernanceSubmissionMixin


class GovernanceService(GovernanceCaseMixin, GovernanceSubmissionMixin, GovernanceSchedulingMixin):
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self._published_cases: dict[str, GovernanceCase] = {}
        self._candidate_cases = contextvars.ContextVar(f"att-cases-{id(self)}", default=None)
        self.lock = asyncio.Lock()
        self.state_lock = threading.RLock()
        self.tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def cases(self):
        candidate = self._candidate_cases.get()
        return candidate if candidate is not None else self._published_cases

    @cases.setter
    def cases(self, values):
        self._published_cases = values

    @asynccontextmanager
    async def stage(self):
        """Keep candidate ballots private until the exact operation is acknowledged."""
        if self._candidate_cases.get() is not None:
            raise RuntimeError("Governance transactions cannot be nested.")
        candidate = dict(self._published_cases)
        token = self._candidate_cases.set(candidate)
        try:
            yield candidate
        finally:
            self._candidate_cases.reset(token)

    def publish(self, candidate):
        with self.state_lock:
            self._published_cases = candidate

    def snapshot(self) -> list[dict[str, Any]]:
        with self.state_lock:
            return [item.model_dump(mode="json") for item in self.cases.values()]

    def restore(self, rows, *, interrupted: bool = True) -> None:
        self.cases = {
            item.case_id: item
            for item in (GovernanceCase.model_validate(row, strict=False) for row in rows)
        }
        if interrupted:
            for item in self.cases.values():
                if item.business_kind == "failover" and item.status == "PENDING":
                    item.status = "EXPIRED"
                    item.reason = "The original model invocation ended when its process stopped."
                    item.resolved_at = time.time()

    def latest(self, business_kind: str, business_id: str, principal: Any):
        with self.state_lock:
            candidates = [
                item
                for item in self.cases.values()
                if item.business_kind == business_kind
                and item.business_id == business_id
                and item.principal == principal
            ]
            return max(candidates, key=lambda item: item.electorate_revision, default=None)

    def is_outstanding(self, agent_id: str, case_id: Any) -> bool:
        item = self.cases.get(case_id) if isinstance(case_id, str) else None
        return bool(
            item
            and item.status == "PENDING"
            and self.business_pending(item)
            and agent_id in item.voter_agent_ids
            and not any(ballot.voter_agent_id == agent_id for ballot in item.ballots)
        )

    def inspect(self, actor, case_id):
        item = self.cases.get(case_id)
        if item is None or actor.agent_id not in item.voter_agent_ids:
            raise PermissionError("The governance case is not addressed to this Agent.")
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

    async def expire(self, case_id: str, reason: str) -> None:
        async with self.lock, self.stage() as candidate:
            item = self.cases[case_id]
            if item.status != "PENDING":
                return
            previous = item
            item = item.model_copy(deep=True)
            self.cases[case_id] = item
            item.status = "EXPIRED"
            item.reason = reason
            item.resolved_at = self.manager._activity.clock.wall_time()
            dirty = self.manager._new_dirty_state()
            dirty["governance_cases"].add(case_id)
            try:
                await self.manager._records.commit((), dirty=dirty, operation_id=f"EXPIRE-{case_id}",
                    governance_state=candidate, allow_closing=self.manager._closing)
            except BaseException:
                if f"EXPIRE-{case_id}" not in self.manager._records.receipts:
                    self.cases[case_id] = previous
                raise
