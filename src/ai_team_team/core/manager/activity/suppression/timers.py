"""One checkpoint loop batches countdown samples; expiry owns one admission."""

import asyncio
import contextvars
from contextlib import contextmanager

from ..values import capture


class CountdownMixin:
    @contextmanager
    def countdown_handoff(self):
        """Own this runtime after the restore wait and before any lock await.

        Restore must reject an admitted handoff even when its mutation lock is
        briefly released for a queued waiter. Dormant timers hold no admission.
        """
        token = object()
        self.countdown_handoffs.add(token)
        try:
            yield
        finally:
            self.countdown_handoffs.discard(token)

    def has_active_countdowns(self):
        active = {owner for owner, agent in self.manager._agents_by_id.items() if agent.lifecycle_state == "active"}
        return any(owner in active and session.intent == "sleep" for owner, session in self.sessions.items()) or any(
            row.table_name == "notification_suppression" and row.values["agent_id"] in active
            and row.values["status"] == "active" and not row.values["permanent"] for row in self.manager._records.snapshot())

    def cancel_suppression_timer(self, preference_id):
        task = self.suppression_timers.pop(preference_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def arm_suppression(self, row):
        preference_id = row.values["preference_id"]
        self.cancel_suppression_timer(preference_id)
        deadline = self.suppression_deadlines.setdefault(preference_id,
            self.clock.monotonic() + row.values["remaining_seconds"])
        generation = self.generation

        async def expire():
            try:
                await self.clock.sleep(max(0.0, deadline - self.clock.monotonic()))
                await self.restore_finished.wait()
                with self.countdown_handoff():
                    if self.generation != generation or row.identity not in self.manager._records.index:
                        return
                    if not self.closing:
                        await self.end_suppression(preference_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.manager._emit_callback("on_system_event", "suppression_expiration_deferred",
                    {"preference_id": preference_id, "error_type": type(error).__name__})
            finally:
                if self.suppression_timers.get(preference_id) is asyncio.current_task():
                    self.suppression_timers.pop(preference_id, None)

        self.suppression_timers[preference_id] = asyncio.create_task(expire(), context=contextvars.Context(),
            name=f"att-suppression-{preference_id}")

    async def sample_suppression(self):
        rows = [capture(self.manager, "notification_suppression", preference_id=row.values["preference_id"],
                    remaining_seconds=self.suppression_remaining(row), sampled_at=self.clock.wall_time())
            for row in self.manager._records.snapshot() if row.table_name == "notification_suppression"
            and row.values["status"] == "active" and not row.values["permanent"]]
        if rows:
            await self.manager._records.commit(rows, allow_closing=self.closing)

    def ensure_countdown_sampler(self):
        if self.closing or self.manager._restore_in_progress or self.countdown_sampler is not None and not self.countdown_sampler.done():
            return
        if not self.has_active_countdowns():
            return
        async def sample():
            try:
                while not self.closing:
                    await self.clock.sleep(self.manager.config.activity.countdown_checkpoint_seconds)
                    await self.restore_finished.wait()
                    with self.countdown_handoff():
                        if self.closing:
                            return
                        if not self.has_active_countdowns():
                            return
                        await self.sample_countdowns()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.fatal_errors.append(error)
                self.manager._emit_callback("on_system_event", "countdown_checkpoint_failed", {"error_type": type(error).__name__})
        self.countdown_sampler = asyncio.create_task(sample(), context=contextvars.Context(), name="att-countdown-checkpoints")

    def restore_suppression_deadlines(self, restoration_start):
        self.suppression_deadlines = {row.values["preference_id"]: restoration_start + row.values["remaining_seconds"]
            for row in self.manager._records.snapshot() if row.table_name == "notification_suppression"
            and row.values["status"] == "active" and not row.values["permanent"]}

    def resume_suppression_timers(self):
        for row in self.manager._records.snapshot():
            if (row.table_name == "notification_suppression" and row.values["status"] == "active"
                    and not row.values["permanent"]):
                owner = self.manager._agents_by_id.get(row.values["agent_id"])
                if owner is not None and owner.lifecycle_state == "active":
                    self.arm_suppression(row)
        self.ensure_countdown_sampler()
