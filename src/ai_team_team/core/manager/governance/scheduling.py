"""Detached notices and authority finalizers with no nested Agent calls."""

import asyncio
import contextvars


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
        self.manager._emergency_tasks.add(task)

        def completed(done):
            if self.tasks.get(key) is done:
                self.tasks.pop(key, None)
            self.manager._emergency_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                self.manager.logger.exception("Governance notification or finalization failed.")

        task.add_done_callback(completed)

    def schedule_notifications(self, item):
        for agent_id in item.voter_agent_ids:
            if self.is_outstanding(agent_id, item.round_id):
                self.track(
                    f"mail:{item.round_id}:{agent_id}", self.notify_agent(item.round_id, agent_id)
                )

    async def notify_agent(self, round_id, agent_id):
        item = self.rounds.get(round_id)
        actor = self.manager._agents_by_id.get(agent_id)
        if item is None or actor is None or not self.is_outstanding(agent_id, round_id):
            return
        if not self.business_pending(item):
            return
        message = next(
            (
                message
                for message in self.manager._inbox.list(agent_id, unread_only=False)
                if message.payload.get("round_id") == round_id
                and message.message_type == "governance_choice_request"
            ),
            None,
        )
        if message is None:
            return
        team = (
            self.manager.teams.get(item.principal.principal_id)
            if item.principal.kind == "agent_team"
            else None
        )
        await self.manager.execute_agent_interaction(
            actor,
            f"You received a governance voting email `{message.message_id}` for round `{round_id}`. You may use open_agent_mail to inspect it and, independently, submit_governance_choice to express a choice. You may also leave it unanswered. Receiving, reading, or acknowledging the email does not cast a vote.",
            team=team,
        )

    def schedule_resolution(self, item):
        self.track(f"resolve:{item.round_id}", self.resolve(item.round_id))

    async def resolve(self, round_id):
        item = self.rounds.get(round_id)
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

    def resume(self):
        for item in self.rounds.values():
            if item.status in {"APPROVED", "DENIED"} and item.business_kind != "failover":
                self.schedule_resolution(item)
            elif item.status == "PENDING" and item.business_kind != "failover":
                self.schedule_notifications(item)
