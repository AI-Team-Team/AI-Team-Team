"""Atomic personal windows, Journal prerequisites, and activity evidence."""

from ai_team_team.core.activity.contracts import ActivityCheckpoint
from ai_team_team.database.persistence.receipts import settle_commit

from .values import capture


class CheckpointMixin:
    def marker(self, session, **changes):
        previous = self.manager._records.index.get(("agent_activities", (session.agent_id,)))
        values = (
            dict(previous.values)
            if previous
            else {
                "agent_id": session.agent_id,
                "arrival_generation": 0,
                "presentation_generation": 0,
                "context_version": 0,
            }
        )
        values.update(
            intent=session.intent,
            availability=session.availability,
            admission_id=session.admission_id if session.active else None,
            context_version=session.context_version,
        )
        values.update(changes)
        values.pop("state_version", None)
        return capture(self.manager, "agent_activities", **values)

    async def commit(
        self,
        session,
        records=(),
        *,
        window=False,
        inbox=False,
        notifications=(),
        allow_closing=True,
        last_context=None,
    ):
        """Never acknowledge a frame independently of its personal checkpoint."""
        manager = self.manager
        dirty = manager._new_dirty_state()
        read_acknowledgements = tuple(session.pending_chat_read_acknowledgements) if window else ()
        records = (*records, *manager._messaging.read_acknowledgement_records(read_acknowledgements))
        if window:
            dirty["agents"].add(session.agent_id)
            with manager._memory._lock:
                dirty["memory_events"].update(session.pending_event_ids)
                dirty["memory_segments"].update(
                    segment.segment_id
                    for segment in manager._memory.segments.values()
                    if segment.invocation_id == session.invocation_id
                    and segment.agent_id == session.agent_id
                )
        if inbox:
            dirty["agent_inboxes"].add(session.agent_id)
        from .values import identifier

        operation_id = identifier("CHECKPOINT")
        try:
            with manager._resources.settlement():
                return await manager._records.commit(
                    tuple(records),
                    dirty=dirty,
                    notifications=notifications,
                    allow_closing=allow_closing,
                    operation_id=operation_id,
                    agent_contexts={session.agent_id: last_context}
                    if last_context is not None
                    else None,
                )
        finally:
            if operation_id in manager._records.receipts:
                session.pending_event_ids.difference_update(dirty["memory_events"])
                del session.pending_chat_read_acknowledgements[:len(read_acknowledgements)]

    async def checkpoint(self, session, *, end_invocation=False, interrupted=False, extra=()):
        records = list(extra)
        if end_invocation and session.invocation_id:
            invocation = self.manager._records.index.get(
                ("activity_invocations", (session.invocation_id,))
            )
            if invocation is not None and invocation.values["boundary_at"] is None:
                records.append(
                    capture(
                        self.manager,
                        "activity_invocations",
                        **{
                            **{
                                key: value
                                for key, value in invocation.values.items()
                                if key != "state_version"
                            },
                            "boundary_at": max(
                                self.clock.wall_time(), invocation.values["started_at"]
                            ),
                            "interrupted": int(interrupted),
                        },
                    )
                )
        presented = {
            row.values["notification_id"]
            for row in records
            if row.table_name == "notification_claims" and row.values["status"] == "presented"
        }
        previous = self.manager._records.index.get(("agent_activities", (session.agent_id,)))
        presentation = max(
            [
                previous.values["presentation_generation"] if previous else 0,
                *(
                    row.values["arrival_generation"]
                    for row in session.frame_notices
                    if row.values["notification_id"] in presented
                ),
            ]
        )
        records.append(self.marker(session, presentation_generation=presentation))
        # Shield accepted checkpoint settlement, not external provider execution.
        import asyncio

        agent = self.require_agent(session.agent_id)
        previous_context = agent.last_context
        scope = (
            session.pending_scope
            if end_invocation and not interrupted and session.pending_scope is not None
            else session.scope
        )
        next_context = {
            **(previous_context or {}),
            "activity_scope": scope.model_dump(mode="json"),
        }
        accepted = asyncio.create_task(
            self.commit(
                session, records, window=True, allow_closing=True, last_context=next_context
            )
        )
        try:
            await settle_commit(accepted)
        finally:
            if accepted.done() and not accepted.cancelled() and accepted.exception() is None:
                agent.last_context = next_context
                self.publish_checkpoint(session, end_invocation=end_invocation)

    def publish_checkpoint(self, session, *, end_invocation=False):
        """Known receipt success is preserved even if its observer was cancelled."""
        if session.context_version > 0:
            checkpoint = ActivityCheckpoint(
                admission_id=session.admission_id,
                agent_id=session.agent_id,
                context_version=session.context_version,
                intent=session.intent,
            )
            self.checkpoints[session.admission_id] = checkpoint
            self.manager._emit_callback(
                "on_system_event",
                "personal_activity_checkpoint",
                {**checkpoint.model_dump(mode="json"), "availability": session.availability},
            )
            for future, intent in tuple(self.waiters.get(session.admission_id, ())):
                if not future.done() and (intent is None or intent == checkpoint.intent):
                    future.set_result(checkpoint)
        if session.failure is not None:
            for future, _intent in tuple(self.waiters.get(session.admission_id, ())):
                if not future.done():
                    future.set_exception(session.failure)
        if end_invocation:
            session.invocation_id = None
