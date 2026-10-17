"""Finite live wake safeguards; complete suppression recovery is a later gate."""

import asyncio
import contextvars

from .values import capture, identifier


class SleepMixin:
    def sleep_records(self, session, intent):
        session.sleep_id = identifier("SLEEP")
        duration = intent.countdown.total_seconds
        session.sleep_deadline = self.clock.monotonic() + duration
        records = [
            capture(
                self.manager,
                "sleep_plans",
                sleep_id=session.sleep_id,
                agent_id=session.agent_id,
                latest_wake_seconds=duration,
                remaining_seconds=duration,
                sampled_at=self.clock.wall_time(),
                minimum_seconds=self.manager.config.activity.minimum_sleep_minutes * 60,
                maximum_seconds=self.manager.config.activity.maximum_sleep_minutes * 60,
                status="active",
            )
        ]
        for condition in intent.early_conditions:
            records.append(
                capture(
                    self.manager,
                    "sleep_conditions",
                    condition_id=identifier("CONDITION"),
                    sleep_id=session.sleep_id,
                    source_kind=condition.source_kind
                    if condition.kind == "message"
                    else "execution",
                    source_agent_id=condition.source_id
                    if condition.kind == "message" and condition.source_kind == "agent"
                    else None,
                    source_team_id=condition.source_id
                    if condition.kind == "message" and condition.source_kind == "agent_team"
                    else None,
                    execution_id=condition.execution_id if condition.kind == "execution" else None,
                    admitted_generation=session.generation,
                    invalidated=0,
                )
            )
        return records

    def matches_sleep(self, session, notice):
        if notice.values["classification"] != "ordinary":
            return True
        source_kind, source_id = self.notice_source(notice)
        for row in self.manager._records.snapshot():
            if (
                row.table_name == "sleep_conditions"
                and row.values["sleep_id"] == session.sleep_id
                and not row.values["invalidated"]
            ):
                if row.values["source_kind"] == source_kind and source_id in {
                    row.values["source_agent_id"],
                    row.values["source_team_id"],
                    row.values["execution_id"],
                }:
                    return True
        return False

    def arm_timer(self, session, delay, *, recovery=False):
        deadline = self.clock.monotonic() + max(0, delay)
        previous = self.timers.pop(session.agent_id, None)
        if previous is not None and previous is not asyncio.current_task():
            previous.cancel()

        async def wake():
            try:
                await self.clock.sleep(max(0, deadline - self.clock.monotonic()))
                if self.closing or self.manager._agents_by_id.get(session.agent_id) is None:
                    return
                live = self.models.live.get(session.agent_id)
                if live is not None and not live.done():
                    # Do not overlap a cancellation-resistant local provider.
                    live.add_done_callback(lambda _done: self.schedule_activation(session.agent_id))
                    return
                await self.activate(session.agent_id, scope=session.scope)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.manager._emit_callback(
                    "on_system_event",
                    "activity_timer_deferred",
                    {
                        "agent_id": session.agent_id,
                        "error_type": type(error).__name__,
                        "recovery": recovery,
                    },
                )
            finally:
                if self.timers.get(session.agent_id) is asyncio.current_task():
                    self.timers.pop(session.agent_id, None)

        task = asyncio.create_task(
            wake(), context=contextvars.Context(), name=f"att-wake-{session.agent_id}"
        )
        self.timers[session.agent_id] = task

    async def sample_sleep(self, session):
        if session.sleep_id and session.sleep_deadline is not None:
            record = capture(
                self.manager,
                "sleep_plans",
                sleep_id=session.sleep_id,
                remaining_seconds=max(0, session.sleep_deadline - self.clock.monotonic()),
                sampled_at=self.clock.wall_time(),
            )
            await self.commit(session, (record,))

    async def sample_countdowns(self):
        async with self.lock:
            for session in self.sessions.values():
                if session.intent == "sleep":
                    await self.sample_sleep(session)
            await self.sample_cooldowns()

    def cooldown_remaining(self, row):
        values = row.values
        if values["accounting_mode"] == "wall_time":
            return max(0, values["deadline"] - self.clock.wall_time())
        key = values["agent_id"], values["tool_name"]
        # A restored duration is anchored only once in this runtime; wall-clock
        # changes and time spent offline cannot consume an excluded countdown.
        deadline = self.cooldown_deadlines.setdefault(
            key, self.clock.monotonic() + values["remaining_seconds"]
        )
        return max(0, deadline - self.clock.monotonic())

    async def sample_cooldowns(self):
        records = [
            capture(
                self.manager,
                "tool_cooldowns",
                agent_id=row.values["agent_id"],
                tool_name=row.values["tool_name"],
                remaining_seconds=self.cooldown_remaining(row),
                sampled_at=self.clock.wall_time(),
            )
            for row in self.manager._records.snapshot()
            if row.table_name == "tool_cooldowns" and row.values["accounting_mode"] == "remaining"
        ]
        if records:
            await self.manager._records.commit(records, allow_closing=self.closing)
