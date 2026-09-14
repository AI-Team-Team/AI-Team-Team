"""Deferred initial work for newly formed AgentTeams."""

import asyncio
import contextvars
import time

from ....formation import FormationDraftStatus, TeamFormationRequest
from ....team import AgentTeam


class FormationTaskMixin:
    def cancel_for_shutdown(self) -> None:
        """Freezes running drafts before their external waits are cancelled."""
        cancelled_ids = set()
        inbox_ids = set()
        for draft in self.drafts.values():
            if draft.status is not FormationDraftStatus.RUNNING:
                continue
            draft.status = FormationDraftStatus.CANCELLED
            draft.reason = (
                "The manager closed before detached proposal deliberation completed."
            )
            draft.updated_at = time.time()
            cancelled_ids.add(draft.draft_id)
            initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
            if initiator is not None:
                self._notify_agent(
                    initiator.agent_id,
                    "team_formation_draft_cancelled",
                    {"draft_id": draft.draft_id, "request_id": draft.request_id},
                )
                inbox_ids.add(initiator.agent_id)
        if cancelled_ids:
            self.manager._auto_save(
                formation_drafts=cancelled_ids,
                agent_inboxes=inbox_ids,
            )

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
                    old_request = current.model_copy(deep=True)
                    initiator = self.manager._agents_by_id.get(
                        current.initiator_agent_id
                    )
                    old_inboxes = (
                        self._copy_inboxes([initiator])
                        if initiator is not None
                        else {}
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
                        if initiator is not None:
                            self._restore_inboxes([initiator], old_inboxes)
                        raise

        self._track_task(run())

    def _schedule_initial_task(
        self,
        request: TeamFormationRequest,
        team: AgentTeam,
    ) -> None:
        if not request.task:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        async def run() -> None:
            try:
                transcript = await self.manager.execute_team_discussion(
                    team,
                    request.task or "",
                    rounds=self.manager.config.subagent_discussion_rounds,
                )
                message_type = "team_formation_task_completed"
                payload = {
                    "request_id": request.request_id,
                    "team_id": team.team_id,
                    "transcript": transcript,
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message_type = "team_formation_task_failed"
                payload = {
                    "request_id": request.request_id,
                    "team_id": team.team_id,
                    "error_type": type(exc).__name__,
                }
            initiator = self.manager._agents_by_id.get(request.initiator_agent_id)
            if initiator is not None:
                self._notify_agent(initiator.agent_id, message_type, payload)
                self.manager._auto_save(agent_inboxes={initiator.agent_id})

        self._track_task(run())
