"""Frozen electorates, explicit rounds, and durable email delivery."""

import asyncio
import time

from ...governance import GovernanceRound


class GovernanceRoundMixin:
    def electorate(self, principal):
        if principal.kind == "agent":
            agent = self.manager._agents_by_id.get(principal.principal_id)
            if agent is not self.manager.root_ai or agent.lifecycle_state != "active":
                return []
            return [agent]
        team = self.manager.teams.get(principal.principal_id)
        if team is None or team.team_kind != "ordinary":
            return []
        return [agent for agent in team.members if agent.lifecycle_state == "active"]

    def electorate_valid(self, item):
        return {agent.agent_id for agent in self.electorate(item.principal)} == set(
            item.voter_agent_ids
        )

    async def create_round(
        self,
        principal,
        business_kind,
        business_id,
        prompt,
        *,
        transcript="",
        members=None,
        candidates=(),
        metadata=None,
        expires_at=None,
    ):
        async with self.lock:
            if self.manager._closing or self.manager._restore_in_progress:
                raise RuntimeError(
                    "ATTManager cannot accept governance rounds during shutdown or restore."
                )
            voters = list(members) if members is not None else self.electorate(principal)
            voter_ids = [agent.agent_id for agent in voters]
            if not voter_ids or len(voter_ids) != len(set(voter_ids)):
                return None
            if set(voter_ids) != {agent.agent_id for agent in self.electorate(principal)}:
                return None
            previous = self.latest(business_kind, business_id, principal)
            # A closed business request cannot be revived by another discussion.
            if previous is not None and not self.business_pending(previous):
                return previous
            if (
                previous is not None
                and previous.status in {"PENDING", "APPROVED", "DENIED"}
                and set(previous.voter_agent_ids) == set(voter_ids)
            ):
                return previous
            old_round = previous.model_copy(deep=True) if previous is not None else None
            item = GovernanceRound(
                business_kind=business_kind,
                business_id=business_id,
                principal=principal,
                round_number=previous.round_number + 1 if previous else 1,
                choice_kind="model" if business_kind == "failover" else "boolean",
                voter_agent_ids=voter_ids,
                prompt=prompt,
                transcript=transcript,
                candidates=list(candidates),
                metadata=dict(metadata or {}),
                expires_at=expires_at,
            )
            if not self.business_pending(item):
                return None
            if previous is not None and previous.status == "PENDING":
                previous.status = "SUPERSEDED"
                previous.reason = "The eligible membership changed before a complete decision."
                previous.resolved_at = time.time()
            message_ids = []
            self.rounds[item.round_id] = item
            for voter in voters:
                message_ids.append(
                    self.manager._inbox.notify(
                        voter.agent_id,
                        "governance_choice_request",
                        {
                            "round_id": item.round_id,
                            "request_id": business_id,
                            "round_number": item.round_number,
                            "business_kind": business_kind,
                            "principal": principal.model_dump(mode="json"),
                        },
                    )
                )
            dirty = self.manager._new_dirty_state()
            dirty["configs"] = True
            dirty["governance_rounds"].add(item.round_id)
            if previous is not None:
                dirty["governance_rounds"].add(previous.round_id)
            dirty["agent_inboxes"].update(voter_ids)
            try:
                await self.manager._commit_dirty_state(dirty)
            except asyncio.CancelledError:
                self.schedule_notifications(item)
                raise
            except Exception:
                self.rounds.pop(item.round_id, None)
                if old_round is not None:
                    self.rounds[old_round.round_id] = old_round
                for voter in voters:
                    with voter.inbox_lock:
                        voter.agent_inbox = [
                            message
                            for message in voter.agent_inbox
                            if message["message_id"] not in message_ids
                        ]
                raise
        self.manager._emit_callback(
            "on_system_event",
            "governance_mail_delivered",
            {
                "round_id": item.round_id,
                "request_id": business_id,
                "principal": principal.model_dump(mode="json"),
                "message_ids": message_ids,
            },
        )
        self.schedule_notifications(item)
        return item
