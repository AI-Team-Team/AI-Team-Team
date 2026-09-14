"""Deferred initial work for newly formed AgentTeams."""

import asyncio
import contextvars

from ....formation import TeamFormationRequest
from ....team import AgentTeam


class FormationTaskMixin:
    def _schedule_initial_task(
        self,
        request: TeamFormationRequest,
        team: AgentTeam,
    ) -> None:
        if not request.task:
            return
        try:
            loop = asyncio.get_running_loop()
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

        task = loop.create_task(run(), context=contextvars.Context())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
