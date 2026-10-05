"""Strict explicit submissions and majority decisions, never read-receipt votes."""

import asyncio
import json
import time

from ...exceptions import ToolArgumentError, ToolBusinessError
from ...governance import GovernanceBallot, GovernanceSubmissionResult


class GovernanceSubmissionMixin:
    def business_pending(self, item):
        if item.business_kind == "communication":
            request = self.manager.broker.communication_requests.get(item.business_id)
            return request is not None and request.status.value in {"PENDING", "PROCESSING"}
        if item.business_kind == "migration":
            request = self.manager._migration.requests.get(item.business_id)
            return request is not None and request.status == "PENDING"
        return item.expires_at is not None and time.time() < item.expires_at

    @staticmethod
    def tally(item):
        if len(item.ballots) != len(item.voter_agent_ids):
            return
        if item.choice_kind == "boolean":
            approvals = sum(ballot.choice["approved"] is True for ballot in item.ballots)
            denials = len(item.ballots) - approvals
            item.status = (
                "APPROVED"
                if approvals > len(item.ballots) / 2
                else "DENIED"
                if denials > len(item.ballots) / 2
                else "TIED"
            )
            authority = "AgentTeam" if item.principal.kind == "agent_team" else "Agent"
            item.reason = f"Complete {authority} ballot: {approvals} approvals and {denials} denials."
        else:
            winners = [
                alias
                for alias in item.candidates
                if sum(ballot.choice["model_alias"] == alias for ballot in item.ballots)
                > len(item.ballots) / 2
            ]
            item.status = "APPROVED" if len(winners) == 1 else "TIED"
            item.reason = (
                "A model alias received a strict majority."
                if winners
                else "No model alias received a strict majority."
            )
        item.resolved_at = time.time()

    async def submit(self, actor, round_id, choice):
        if self.manager._active_tool_agent.get() is not actor:
            raise PermissionError(
                "Governance choices require the current Agent's explicit tool invocation."
            )
        if (
            self.manager._agents_by_id.get(actor.agent_id) is not actor
            or actor.lifecycle_state != "active"
        ):
            raise PermissionError("Only the addressed active Agent may submit its own choice.")
        async with self.lock:
            if self.manager._closing or self.manager._restore_in_progress:
                raise RuntimeError(
                    "ATTManager cannot accept governance choices during shutdown or restore."
                )
            item = self.rounds.get(round_id)
            if item is None or actor.agent_id not in item.voter_agent_ids:
                raise PermissionError(
                    "This Agent is not an eligible voter for the requested round."
                )
            try:
                validated = self.choice_model(item).model_validate(choice, strict=True)
            except (TypeError, ValueError) as exc:
                raise ToolArgumentError(
                    "The governance choice does not match its strict schema."
                ) from exc
            payload = validated.model_dump(mode="json")
            if item.choice_kind == "model" and payload["model_alias"] not in item.candidates:
                raise ToolArgumentError("The chosen model alias is not an eligible candidate.")
            existing = next(
                (ballot for ballot in item.ballots if ballot.voter_agent_id == actor.agent_id), None
            )
            if existing is not None:
                if existing.choice != payload:
                    raise ToolBusinessError(
                        "An accepted ballot cannot be changed within the same round."
                    )
                return GovernanceSubmissionResult(
                    status="ALREADY_SUBMITTED",
                    round_id=round_id,
                    round_status=item.status,
                    choice=payload,
                )
            previous = item.model_copy(deep=True)
            if item.status != "PENDING":
                return GovernanceSubmissionResult(
                    status="CLOSED", round_id=round_id, round_status=item.status, reason=item.reason
                )
            if not self.electorate_valid(item):
                item.status = "SUPERSEDED"
                item.reason = "AgentTeam membership changed before a complete decision."
                item.resolved_at = time.time()
            elif not self.business_pending(item):
                item.status = "EXPIRED" if item.business_kind == "failover" else "CANCELLED"
                item.reason = "The originating operation no longer accepts choices."
                item.resolved_at = time.time()
            else:
                item.ballots = item.ballots + [
                    GovernanceBallot(
                        round_id=round_id, voter_agent_id=actor.agent_id, choice=payload
                    )
                ]
                self.tally(item)
            dirty = self.manager._new_dirty_state()
            dirty["governance_rounds"].add(round_id)
            actor.sync_message_history()
            history_lengths = (len(actor.messages), len(actor.message_history))
            event = None
            public_message = None
            if len(item.ballots) > len(previous.ballots):
                public_message = {
                    "role": "assistant",
                    "content": "Public governance choice: "
                    + json.dumps(
                        {
                            "round_id": round_id,
                            "request": item.prompt,
                            "principal": item.principal.model_dump(mode="json"),
                            "choice": payload,
                        },
                        sort_keys=True,
                    ),
                    "team_id": self.manager._active_team.get().team_id
                    if self.manager._active_team.get()
                    else None,
                    "discussion_id": self.manager._active_discussion_id.get(),
                }
                # The choice and exact ballot commit together. No email flags are changed.
                # Native tools must return before another ordinary assistant
                # message can enter the provider window. Their normal tool
                # response carries the same public choice instead.
                pending_native_batch = bool(actor.messages and actor.messages[-1].get("tool_calls"))
                if not pending_native_batch:
                    actor.messages.append(public_message)
                actor.message_history.append(public_message)
                actor._history_seen_ids.add(id(public_message))
                event = self.manager._memory.record_event(
                    "message",
                    agent=actor,
                    team=self.manager._active_team.get(),
                    role="assistant",
                    payload=public_message,
                    persist=False,
                )
                dirty["agents"].add(actor.agent_id)
                dirty["memory_events"].add(event.event_id)
            try:
                await self.manager._commit_dirty_state(dirty)
            except asyncio.CancelledError:
                if item.status in {"APPROVED", "DENIED"}:
                    self.schedule_resolution(item)
                if item.status != "PENDING" and (waiter := self.waiters.get(round_id)):
                    waiter.set()
                raise
            except Exception:
                self.rounds[round_id] = previous
                for message in actor.messages[history_lengths[0] :]:
                    actor._history_seen_ids.discard(id(message))
                if public_message is not None:
                    actor._history_seen_ids.discard(id(public_message))
                del actor.messages[history_lengths[0] :]
                del actor.message_history[history_lengths[1] :]
                if event is not None:
                    self.manager._memory.discard_unpersisted_event(event.event_id)
                raise
            if item.status != "PENDING" and (waiter := self.waiters.get(round_id)):
                waiter.set()
        if item.status in {"APPROVED", "DENIED"}:
            self.schedule_resolution(item)
        self.manager._emit_callback(
            "on_system_event",
            "governance_choice_recorded",
            {"round_id": round_id, "agent_id": actor.agent_id, "status": item.status},
        )
        return GovernanceSubmissionResult(
            status="SUBMITTED" if len(item.ballots) > len(previous.ballots) else "CLOSED",
            round_id=round_id,
            round_status=item.status,
            reason=item.reason,
            choice=payload if len(item.ballots) > len(previous.ballots) else None,
        )
