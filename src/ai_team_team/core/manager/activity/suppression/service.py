"""Receipt-owned preferences with live source checks and monotonic expiry."""

from pydantic import TypeAdapter

from ai_team_team.core.activity.contracts import CountdownBounds, SuppressionPreference
from ai_team_team.core.exceptions import ToolArgumentError, ToolPermissionError

from ..values import capture, identifier
from .summaries import SuppressionSummaryMixin
from .timers import CountdownMixin


class SuppressionMixin(SuppressionSummaryMixin, CountdownMixin):
    def suppression_actor(self, actor=None):
        current = self.manager._active_tool_agent.get()
        if current is not None and actor is not None and current is not actor:
            raise ToolPermissionError("Notification preferences cannot select another person.")
        actor = current or actor
        if actor is None or self.require_agent(actor.agent_id) is not actor:
            raise ToolPermissionError("Notification preferences require an explicit active owner.")
        if self.manager.supervisor.is_supervisory_agent(actor.agent_id):
            raise ToolPermissionError("Temporary auditors cannot change personal notification preferences.")
        return actor

    def suppression_remaining(self, row):
        if row.values["permanent"]:
            return None
        if row.values["status"] != "active":
            return row.values["remaining_seconds"]
        deadline = self.suppression_deadlines.setdefault(row.values["preference_id"],
            self.clock.monotonic() + row.values["remaining_seconds"])
        return max(0.0, deadline - self.clock.monotonic())

    def suppression_view(self, row):
        values = row.values
        return {"preference_id": values["preference_id"], "scope": values["scope"],
            "source_id": values["source_agent_id"] or values["source_team_id"],
            "permanent": bool(values["permanent"]), "remaining_seconds": self.suppression_remaining(row),
            "status": values["status"]}

    def list_suppressions(self, *, actor=None, active_only=True):
        actor = self.suppression_actor(actor)
        if type(active_only) is not bool:
            raise ToolArgumentError("active_only must be a boolean.")
        return [self.suppression_view(row) for row in self.manager._records.snapshot()
            if row.table_name == "notification_suppression" and row.values["agent_id"] == actor.agent_id
            and (not active_only or row.values["status"] == "active")]

    def validate_suppression_source(self, owner, preference):
        if preference.scope == "agent":
            self.require_agent(preference.source_id)
        elif preference.scope == "agent_team":
            self.manager._topology.require_available(self.manager.teams.get(preference.source_id))

    async def set_suppression(self, preference, *, actor=None):
        preference = TypeAdapter(SuppressionPreference).validate_python(preference)
        owner = self.suppression_actor(actor)
        async with owner.lifecycle_lock, self.lock:
            self.check_open()
            self.suppression_actor(owner)
            config = self.manager.config.activity
            bounds = CountdownBounds(minimum_minutes=config.minimum_sleep_minutes,
                                     maximum_minutes=config.maximum_sleep_minutes)
            try:
                preference.check_bounds(bounds)
                self.validate_suppression_source(owner, preference)
            except ValueError as error:
                raise ToolArgumentError(str(error)) from error
            duration = preference.countdown.total_seconds if preference.countdown else None
            preference_id = identifier("SUPPRESSION")
            deadline = self.clock.monotonic() + duration if duration is not None else None
            row = capture(self.manager, "notification_suppression", preference_id=preference_id,
                agent_id=owner.agent_id, scope=preference.scope,
                source_agent_id=preference.source_id if preference.scope == "agent" else None,
                source_team_id=preference.source_id if preference.scope == "agent_team" else None,
                permanent=int(duration is None), remaining_seconds=duration, sampled_at=self.clock.wall_time(),
                status="active", duration_seconds=duration,
                minimum_seconds=bounds.minimum_minutes * 60 if duration is not None else None,
                maximum_seconds=bounds.maximum_minutes * 60 if duration is not None else None)
            operation = f"SET-{preference_id}"
            try:
                await self.manager._records.commit((row,), operation_id=operation,
                    authority_check=lambda: (self.suppression_actor(owner), self.validate_suppression_source(owner, preference)))
            finally:
                if operation in self.manager._records.receipts:
                    if deadline is not None:
                        self.suppression_deadlines[preference_id] = deadline
                        self.arm_suppression(row)
                    self.ensure_countdown_sampler()
            return self.suppression_view(row)

    async def remove_suppression(self, preference_id, *, actor=None):
        owner = self.suppression_actor(actor)
        return await self.end_suppression(preference_id, owner=owner, status="removed")

    async def end_suppression(self, preference_id, *, owner=None, status="expired"):
        async with self.lock:
            self.check_open()
            row = self.manager._records.index.get(("notification_suppression", (preference_id,)))
            if row is None or owner is not None and row.values["agent_id"] != self.suppression_actor(owner).agent_id:
                raise ToolPermissionError("The notification preference does not belong to this person.")
            if row.values["status"] != "active":
                return self.suppression_view(row)
            self.require_agent(row.values["agent_id"])
            remaining = self.suppression_remaining(row)
            updated = capture(self.manager, "notification_suppression", preference_id=preference_id,
                status=status, remaining_seconds=remaining, sampled_at=self.clock.wall_time())
            records, notice_ids, events = self.suppression_summary_records(row)
            dirty = self.manager._new_dirty_state()
            dirty["memory_events"].update(events)
            operation = f"END-{preference_id}"
            try:
                await self.manager._records.commit((updated, *records), operation_id=operation,
                    dirty=dirty, notifications=notice_ids)
            finally:
                if operation in self.manager._records.receipts:
                    self.cancel_suppression_timer(preference_id)
                    self.suppression_deadlines.pop(preference_id, None)
                    for notice in self.pending_notices(row.values["agent_id"]):
                        self.schedule_notice(notice.values["notification_id"])
                else:
                    for event_id in events:
                        self.manager._memory.discard_unpersisted_event(event_id)
            return self.suppression_view(updated)

    def preference_matches(self, preference, notice):
        values = preference.values
        if values["agent_id"] != notice.values["agent_id"] or notice.values["classification"] != "ordinary":
            return False
        if values["scope"] == "all":
            return True
        return self.notice_source(notice) == (values["scope"], values["source_agent_id"] or values["source_team_id"])

    def suppressed_except(self, notice, excluded=()):
        if notice.values["classification"] != "ordinary":
            return False
        return any(row.table_name == "notification_suppression" and row.values["preference_id"] not in excluded
            and row.values["status"] == "active" and self.preference_matches(row, notice)
            for row in self.manager._records.snapshot())
