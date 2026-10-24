"""Detached notices and authority finalizers with no nested Agent calls."""

import asyncio
import contextvars

from ...exceptions import RuntimeAdmissionClosedError


class GovernanceSchedulingMixin:
    def track(self, key, coroutine):
        current = self.tasks.get(key)
        if self.manager._closing or current is not None and not current.done():
            coroutine.close()
            return
        task = asyncio.create_task(
            coroutine, name=f"att-governance-{key}", context=contextvars.Context()
        )
        self.tasks[key] = task
        self.manager._institutional_tasks.add(task)

        def completed(done):
            if self.tasks.get(key) is done:
                self.tasks.pop(key, None)
            self.manager._institutional_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except RuntimeAdmissionClosedError:
                self.manager._emit_callback("on_system_event", "governance_admission_deferred",
                    {"operation_key": key, "reason": "runtime_admission_closed"})
            except Exception:
                self.manager.logger.exception("Governance notification or finalization failed.")

        task.add_done_callback(completed)

    def schedule_notifications(self, item):
        for agent_id in item.voter_agent_ids:
            if self.is_outstanding(agent_id, item.case_id):
                for mail in self.manager._inbox.list(agent_id, unread_only=False):
                    if mail.message_type == "governance_choice_request" and mail.payload.get("case_id") == item.case_id:
                        notice_id = f"NOTICE-{mail.message_id}"
                        if ("agent_notifications", (notice_id,)) in self.manager._records.index:
                            self.manager._activity.schedule_notice(notice_id)

    async def notify_agent(self, case_id, agent_id):
        item = self.cases.get(case_id)
        actor = self.manager._agents_by_id.get(agent_id)
        if item is None or actor is None or not self.is_outstanding(agent_id, case_id):
            return
        if not self.business_pending(item):
            return
        message = next(
            (
                message
                for message in self.manager._inbox.list(agent_id, unread_only=False)
                if message.payload.get("case_id") == case_id
                and message.message_type == "governance_choice_request"
            ),
            None,
        )
        if message is None:
            return
        notice_id = f"NOTICE-{message.message_id}"
        if ("agent_notifications", (notice_id,)) in self.manager._records.index:
            self.manager._activity.schedule_notice(notice_id)

    def schedule_resolution(self, item):
        self.track(f"resolve:{item.case_id}", self.resolve(item.case_id))

    def memberships_changed(self, team_ids):
        for item in tuple(self.cases.values()):
            if (item.principal.kind == "agent_team" and item.principal.principal_id in team_ids
                    and self.business_pending(item) and not self.electorate_valid(item)):
                self.track(f"renew:{item.business_kind}:{item.business_id}:{item.principal.key}",
                    self.create_case(item.principal, item.business_kind, item.business_id, item.prompt,
                        candidates=item.candidates, metadata=item.metadata, expires_at=item.expires_at))

    async def resolve(self, case_id):
        item = self.cases.get(case_id)
        if item is None or item.status not in {"APPROVED", "DENIED"}:
            return
        if item.business_kind == "communication":
            from ...communication import CommunicationApprovalStatus

            approval = self.manager.broker.communication_approvals.get(
                f"{item.business_id}:{item.principal.key}"
            )
            if approval is None:
                return
            if approval.status is CommunicationApprovalStatus.PENDING:
                approval = await self.manager.broker._claim_approval(
                    item.business_id, item.principal
                )
            if approval is None:
                return
            outcome = self.manager.broker.decision_provider.outcome(item)
            await self.manager.broker._complete_approval(item.business_id, item.principal, outcome)
        elif item.business_kind == "migration":
            await self.manager._migration.complete_request(item.business_id)
        elif item.business_kind == "failover":
            await self.manager._failover.resolve(item.business_id)

    def resume(self):
        for item in self.cases.values():
            if item.status in {"APPROVED", "DENIED"} and item.business_kind != "failover":
                self.schedule_resolution(item)
            elif item.status == "PENDING" and item.business_kind != "failover":
                self.schedule_notifications(item)
