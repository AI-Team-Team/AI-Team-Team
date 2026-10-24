"""Post-publication personal admission, never external execution replay."""

from .persisted_context import restored_activity_scope
from .values import Session, capture


class ActivityRecoveryMixin:
    async def after_restore(self, *, restoration_start):
        from ai_team_team.core.exceptions import StateRestoreError

        self.recovery_required = True
        for session in self.sessions.values():
            for _mail_id, future in tuple(session.interaction_waiters):
                if not future.done():
                    future.set_exception(
                        StateRestoreError("Restore replaced the observed activity generation.")
                    )
        for waiters in self.waiters.values():
            for future, _intent in waiters:
                if not future.done():
                    future.set_exception(
                        StateRestoreError("Restore replaced the observed activity generation.")
                    )
        for task in self.timers.values():
            task.cancel()
        self.timers.clear()
        self.sessions.clear()
        self.admissions.clear()
        self.checkpoints.clear()
        self.cooldown_deadlines.clear()
        self._restored_actions = []
        records = self.manager._records.snapshot()
        for row in records:
            if row.table_name == "tool_cooldowns" and row.values["accounting_mode"] == "remaining":
                self.cooldown_deadlines[(row.values["agent_id"], row.values["tool_name"])] = (
                    restoration_start + row.values["remaining_seconds"]
                )
        tracked = {
            row.values["agent_id"] for row in records if row.table_name == "agent_activities"
        }
        reset = []
        requests = {
            row.values["model_request_id"]: row
            for row in records
            if row.table_name == "model_requests"
            and row.values["agent_id"] in tracked
            and row.values["outcome"] == "pending"
        }
        for row in records:
            if row.table_name == "executions" and row.values["status"] in {"queued", "running"}:
                reset.append(capture(self.manager, "executions", execution_id=row.values["execution_id"],
                                     outcome_unconfirmed=1, attention="required"))
            if (
                row.table_name == "activity_admissions"
                and row.values["agent_id"] in tracked
                and row.values["disposition"] == "admitted"
            ):
                reset.append(
                    capture(
                        self.manager,
                        row.table_name,
                        admission_id=row.values["admission_id"],
                        disposition="interrupted",
                    )
                )
            if (
                row.table_name == "activity_invocations"
                and row.values["agent_id"] in tracked
                and row.values["boundary_at"] is None
            ):
                reset.append(
                    capture(
                        self.manager,
                        row.table_name,
                        invocation_id=row.values["invocation_id"],
                        boundary_at=max(self.clock.wall_time(), row.values["started_at"]),
                        interrupted=1,
                    )
                )
            if row.table_name == "model_requests" and row.values["model_request_id"] in requests:
                unsent = row.values["dispatch_state"] == "unsent"
                reset.append(
                    capture(
                        self.manager,
                        row.table_name,
                        model_request_id=row.values["model_request_id"],
                        dispatch_state="confirmed_unsent" if unsent else "unknown_sent",
                        outcome="cancelled" if unsent else "uncertain",
                    )
                )
            if (
                row.table_name == "model_token_claims"
                and row.values["model_request_id"] in requests
                and row.values["settlement"] == "reserved"
            ):
                unsent = (
                    requests[row.values["model_request_id"]].values["dispatch_state"] == "unsent"
                )
                reset.append(
                    capture(
                        self.manager,
                        row.table_name,
                        claim_id=row.values["claim_id"],
                        settlement="confirmed_unsent" if unsent else "unknown_sent",
                        settled_at=self.clock.wall_time(),
                    )
                )
            if (
                row.table_name == "notification_claims"
                and row.values["model_request_id"] in requests
                and row.values["status"] != "presented"
            ):
                reset.append(
                    capture(
                        self.manager,
                        row.table_name,
                        notification_id=row.values["notification_id"],
                        model_request_id=row.values["model_request_id"],
                        status="uncertain",
                        observed_at=self.clock.wall_time(),
                    )
                )
        if reset:
            # This is post-publication bookkeeping. It cannot contaminate a
            # prepared generation's rollback with updates to existing facts.
            await self.manager._records.commit(reset, allow_closing=True)
            records = self.manager._records.snapshot()
        affected = set(
            getattr(getattr(self.manager, "_recovery_plan", None), "affected_agents", ())
        )
        for row in records:
            if row.table_name != "agent_activities":
                continue
            owner = row.values["agent_id"]
            agent = self.manager._agents_by_id.get(owner)
            if agent is None or agent.lifecycle_state != "active":
                continue
            scope = restored_activity_scope(agent.last_context, owner, records)
            session = Session(
                owner,
                row.values["admission_id"] or f"RESTORED-{owner}",
                self.generation,
                scope=scope,
                context_version=row.values["context_version"],
                active=False,
                intent=row.values["intent"],
                availability=row.values["availability"],
            )
            self.sessions[owner] = session
            sleep = next(
                (
                    item
                    for item in records
                    if item.table_name == "sleep_plans"
                    and item.values["agent_id"] == owner
                    and item.values["status"] == "active"
                ),
                None,
            )
            if sleep is not None:
                session.sleep_id = sleep.values["sleep_id"]
                session.sleep_deadline = restoration_start + sleep.values["remaining_seconds"]
            self._restored_actions.append((session, owner in affected))
        self.recovery_required = False

    def resume_after_restore(self):
        """Publish queue/timer handoffs only after every local index is coherent."""
        actions, self._restored_actions = self._restored_actions, []
        for session, affected in actions:
            owner = session.agent_id
            agent = self.manager._agents_by_id[owner]
            if affected or session.intent == "continuing":
                try:
                    alias = self.manager.resolve_runtime_model_alias(agent.llm_client)
                    availability = self.manager._records.index.get(
                        ("model_availability", (owner, alias))
                    )
                    if (
                        availability is not None
                        and availability.values["status"] == "remediation_required"
                    ):
                        continue
                    if (
                        availability is not None
                        and availability.values["earliest_admission_at"] is not None
                    ):
                        delay = max(
                            0, availability.values["earliest_admission_at"] - self.clock.wall_time()
                        )
                        self.arm_timer(session, delay, recovery=True)
                    else:
                        self.schedule_activation(owner)
                except Exception as error:
                    self.manager._emit_callback(
                        "on_system_event",
                        "activity_recovery_deferred",
                        {"agent_id": owner, "error_type": type(error).__name__},
                    )
            elif session.intent == "sleep":
                if session.sleep_id is not None:
                    self.arm_timer(session, max(0, session.sleep_deadline - self.clock.monotonic()))
            for notice in self.pending_notices(owner):
                self.schedule_notice(notice.values["notification_id"])
