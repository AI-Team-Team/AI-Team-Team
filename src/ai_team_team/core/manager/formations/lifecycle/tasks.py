"""Deferred initial work for newly formed AgentTeams."""

import asyncio
import contextvars
import time

from ....formation import TeamFormationRequest
from ....exceptions import RuntimeAdmissionClosedError
from ....team import AgentTeam


class FormationTaskMixin:
    def _track_task(self, coroutine: object) -> asyncio.Task[object]:
        """Starts framework-owned work without inheriting invocation dependencies."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(coroutine, context=contextvars.Context())
        self.tasks.add(task)

        def finish(completed: asyncio.Task[object]) -> None:
            self.tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is None:
                return
            if isinstance(error, RuntimeAdmissionClosedError):
                self._emit_event("team_formation_admission_deferred", {"reason": "runtime_admission_closed"})
                return
            self.manager.logger.error(
                "Detached team-formation task failed: %s",
                type(error).__name__,
            )
            self._emit_event(
                "team_formation_background_task_failed",
                {"error_type": type(error).__name__},
            )

        task.add_done_callback(finish)
        return task

    def _schedule_empty_auto_creation(self, request: TeamFormationRequest) -> None:
        """Creates an eligible initiator-only/new-Agent proposal without a response trigger."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        async def run() -> None:
            async with self.request_lock(request.request_id):
                current = self.requests.get(request.request_id)
                if current is None or current.proposal_revision != request.proposal_revision:
                    return
                if current.status.value not in {
                    "collecting_responses",
                    "ready_for_confirmation",
                }:
                    return
                try:
                    await self._finalize_locked(current, automatic=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # The finalizer may have replaced its rejected candidate
                    # with the prior projection. Never report failure on the
                    # detached candidate or rewrite an accepted creation.
                    current = self.requests.get(request.request_id)
                    if current is None:
                        return
                    if current.status.value == "created":
                        raise
                    old_request = current.model_copy(deep=True)
                    initiator = self.manager._agents_by_id.get(
                        current.initiator_agent_id
                    )
                    current.decision_reason = (
                        "Automatic creation could not commit: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    current.updated_at = time.time()
                    try:
                        if initiator is not None:
                            self._notify_agent(
                                initiator.agent_id,
                                "team_formation_auto_create_failed",
                                {
                                    "request_id": current.request_id,
                                    "proposal_revision": current.proposal_revision,
                                    "error_type": type(exc).__name__,
                                },
                            )
                        await self.manager._commit_dirty_state(
                            self._dirty(
                                current.request_id,
                                inbox_agent_ids=(
                                    {initiator.agent_id}
                                    if initiator is not None
                                    else set()
                                ),
                            )
                        )
                    except Exception:
                        self.requests[current.request_id] = old_request
                        raise

        self._track_task(run())

    def prepare_initial_instructions(self, team, text):
        """Capture addressed input, not a required business work-item lifecycle."""
        for member in team.members:
            self.manager._inbox.notify(member.agent_id, "team_initial_instruction",
                {"team_id": team.team_id, "text": text}, message_id=f"INITIAL-{team.team_id}-{member.agent_id}")

    def schedule_initial_arrivals(self, team):
        if not any(any(mail["message_type"] == "team_initial_instruction" and mail["payload"].get("team_id") == team.team_id
                       for mail in member.agent_inbox) for member in team.members):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        async def admit():
            from ....activity.contracts import AgentTeamScope
            for member in tuple(team.members):
                if self.manager._closing or getattr(team, "_lifecycle_state", "active") != "active":
                    return
                if not any(mail["message_type"] == "team_initial_instruction"
                           and mail["payload"].get("team_id") == team.team_id for mail in member.agent_inbox):
                    continue
                async with self.manager._activity.lock:
                    if self.manager._closing or self.manager._restore_in_progress:
                        return
                    records, notices = self.manager._activity.mail_records({member.agent_id})
                    if records:
                        dirty = self.manager._new_dirty_state()
                        dirty["agent_inboxes"].add(member.agent_id)
                        await self.manager._records.commit(records, dirty=dirty, notifications=notices)
                    pending = self.manager._activity.pending_notices(member.agent_id)
                    if pending and member in team.members and not self.manager._closing and not self.manager._restore_in_progress:
                        await self.manager._activity._activate_locked(member.agent_id,
                            scope=AgentTeamScope(team_id=team.team_id))

        self._track_task(admit())
