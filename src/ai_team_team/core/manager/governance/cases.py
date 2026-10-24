"""Frozen electorate revisions and voluntary durable personal mail."""

import asyncio

from ...governance import GovernanceCase
from ...exceptions import RuntimeAdmissionClosedError


class _CaseAdmissionChanged(Exception):
    """A legitimate concurrent lifecycle boundary invalidated this solicitation."""


class GovernanceCaseMixin:
    def electorate(self, principal):
        if principal.kind == "agent":
            agent = self.manager._agents_by_id.get(principal.principal_id)
            if agent is None or agent.lifecycle_state != "active" or self.manager._topology.is_agent_pending(agent.agent_id):
                return []
            return [agent]
        team = self.manager.teams.get(principal.principal_id)
        if (team is None or team.team_kind != "ordinary" or getattr(team, "_publication_pending", False)
                or getattr(team, "_lifecycle_state", "active") != "active"):
            return []
        return [agent for agent in team.members if agent.lifecycle_state == "active"]

    def electorate_bindings(self, principal):
        if principal.kind == "agent":
            return {}
        return {row.values["agent_id"]: row.values["interval_id"] for row in self.manager._records.snapshot()
            if row.table_name == "membership_intervals" and row.values["team_id"] == principal.principal_id
            and row.values["leave_event_id"] is None}

    def electorate_valid(self, item):
        return ({agent.agent_id for agent in self.electorate(item.principal)} == set(item.voter_agent_ids)
                and self.electorate_bindings(item.principal) == item.electorate_bindings)

    async def create_case(
        self,
        principal,
        business_kind,
        business_id,
        prompt,
        *,
        candidates=(),
        metadata=None,
        expires_at=None,
    ):
        async with self.lock, self.stage() as candidate:
            if self.manager._closing or self.manager._restore_in_progress:
                raise RuntimeAdmissionClosedError(
                    "ATTManager cannot accept governance cases during shutdown or restore."
                )
            voters = self.electorate(principal)
            voter_ids = [agent.agent_id for agent in voters]
            bindings = self.electorate_bindings(principal)
            if principal.kind == "agent_team" and set(bindings) != set(voter_ids):
                return None
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
                and self.electorate_valid(previous)
            ):
                return previous
            old_case = previous
            if previous is not None:
                previous = previous.model_copy(deep=True)
                self.cases[previous.case_id] = previous
            item = GovernanceCase(
                business_kind=business_kind,
                business_id=business_id,
                principal=principal,
                electorate_revision=previous.electorate_revision + 1 if previous else 1,
                choice_kind="model" if business_kind == "failover" else "boolean",
                voter_agent_ids=voter_ids,
                electorate_bindings=bindings,
                prompt=prompt,
                candidates=list(candidates),
                metadata=dict(metadata or {}),
                expires_at=expires_at,
                created_at=self.manager._activity.clock.wall_time(),
            )
            if not self.business_pending(item):
                return None
            if previous is not None and previous.status == "PENDING":
                previous.status = "SUPERSEDED"
                previous.reason = "The eligible membership changed before a complete decision."
                previous.resolved_at = self.manager._activity.clock.wall_time()
            message_ids = []
            self.cases[item.case_id] = item
            for voter in voters:
                message_ids.append(
                    self.manager._inbox.notify(
                        voter.agent_id,
                        "governance_choice_request",
                        {
                            "case_id": item.case_id,
                            "request_id": business_id,
                            "electorate_revision": item.electorate_revision,
                            "business_kind": business_kind,
                            "principal": principal.model_dump(mode="json"),
                        },
                        staged=True,
                    )
                )
            dirty = self.manager._new_dirty_state()
            dirty["configs"] = True
            dirty["governance_cases"].add(item.case_id)
            if previous is not None:
                dirty["governance_cases"].add(previous.case_id)
            dirty["agent_inboxes"].update(voter_ids)
            operation_id = f"CASE-{item.case_id}"
            notice_ids = ()
            try:
                async with self.manager._activity.lock:
                    if not self.electorate_valid(item) or not self.business_pending(item):
                        raise _CaseAdmissionChanged
                    records, notice_ids = self.manager._activity.mail_records(set(voter_ids))
                    if business_kind == "failover":
                        from ..activity.values import capture
                        records.append(capture(self.manager, "resource_decisions", attempt_id=business_id,
                            decision_case_id=item.case_id))
                    await self.manager._records.commit(records, dirty=dirty, notifications=notice_ids,
                        operation_id=operation_id, governance_state=candidate)
            except BaseException as error:
                if operation_id not in self.manager._records.receipts:
                    self.cases.pop(item.case_id, None)
                    if old_case is not None:
                        self.cases[old_case.case_id] = old_case
                    for voter in voters:
                        with voter.inbox_lock:
                            voter.agent_inbox[:] = [
                                message for message in voter.agent_inbox if message["message_id"] not in message_ids
                            ]
                if isinstance(error, _CaseAdmissionChanged):
                    return None
                raise
            finally:
                self.manager._inbox.finish_staged(message_ids)
                if operation_id in self.manager._records.receipts:
                    self.schedule_notifications(item)

        self.manager._emit_callback(
            "on_system_event",
            "governance_mail_delivered",
            {
                "case_id": item.case_id,
                "request_id": business_id,
                "principal": principal.model_dump(mode="json"),
                "message_ids": message_ids,
            },
        )
        self.schedule_notifications(item)
        return item
