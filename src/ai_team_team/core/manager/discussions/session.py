"""Multi-round discussion session implementation."""

import asyncio
import uuid
from typing import TYPE_CHECKING, List

from ...exceptions import AgentTurnIncompleteError, ATTException
from ...team import AgentTeam
from .audit import audit_discussion
from .cleanup import finalize_discussion_session
from .inbox import prepare_inbox_context
from .reporting import emit_discussion_log

if TYPE_CHECKING:
    from ...response import DiscussionResult


class DiscussionSessionMixin:
    async def _execute_team_discussion_session(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
        require_complete: bool = False,
    ) -> "DiscussionResult":
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor."""
        with self.manager._topology_lock:
            team.migration_count = 0
        team.is_running = True
        self.manager.logger.info(
            f"Executing discussion in team {team.team_id} (rounds={rounds}, skip_audit={skip_audit})..."
        )

        dialog_history = []
        last_round_answers = {}
        from ...response import (
            AgentTurnResult,
            AgentTurnStatus,
            AuditResult,
            AuditStatus,
            DiscussionResult,
            DiscussionRoundResult,
            DiscussionStatus,
            OperationalStatus,
        )

        discussion_token = self.manager._active_discussion_id.set(f"DISC-{uuid.uuid4().hex}")
        processed_unknown_fingerprints: set[str] = set()
        processed_operational_fingerprints: set[str] = set()
        processed_communication_request_ids: set[str] = set()
        processed_peer_message_ids: set[str] = set()
        communication_member_snapshot = list(team.members)
        discussion_had_member_errors = False
        discussion_succeeded = False
        structured_rounds: List[DiscussionRoundResult] = []

        auto_save_context = self.manager.suppress_auto_save()
        await auto_save_context.__aenter__()
        try:
            for r in range(1, rounds + 1):
                inbox_context = await prepare_inbox_context(
                    self.manager,
                    team,
                    processed_unknown_fingerprints,
                    processed_operational_fingerprints,
                    processed_communication_request_ids,
                    processed_peer_message_ids,
                )

                round_members = list(team.members)
                tasks = []
                for agent in round_members:
                    if r == 1:
                        round_prompt = f"{prompt}{inbox_context}"
                    else:
                        other_answers = []
                        for other_agent in round_members:
                            if other_agent.name != agent.name:
                                ans = last_round_answers.get(
                                    (r - 1, other_agent.name), "No response."
                                )
                                other_answers.append(
                                    f"{other_agent.name} (Role: {other_agent.role}): {ans}"
                                )

                        round_prompt = (
                            f"Here is the discussion from Round {r - 1}:\n"
                            + "\n".join(other_answers)
                            + "\n\n"
                            f"Please continue the discussion. Build on or challenge their arguments."
                            f"{inbox_context}"
                        )

                    async def _run_agent(ag=agent, pr=round_prompt):
                        round_token = self.manager._active_round_number.set(r)
                        try:
                            public_method = team.execute_reasoning_step
                            if (
                                getattr(public_method, "__func__", None)
                                is not AgentTeam.execute_reasoning_step
                            ):
                                raw = await public_method(
                                    agent=ag,
                                    prompt=pr,
                                    system_instruction=team.system_instructions,
                                    max_steps=self.manager.config.react_max_steps,
                                    manager=self.manager,
                                )
                                if isinstance(raw, AgentTurnResult):
                                    return raw
                                return AgentTurnResult(
                                    agent_id=ag.agent_id,
                                    team_id=team.team_id,
                                    discussion_id=self.manager._active_discussion_id.get(),
                                    round_number=r,
                                    status=AgentTurnStatus.COMPLETED,
                                    answer=str(raw),
                                )
                            return await team.execute_reasoning_step_detailed(
                                agent=ag,
                                prompt=pr,
                                system_instruction=team.system_instructions,
                                max_steps=self.manager.config.react_max_steps,
                                manager=self.manager,
                            )
                        finally:
                            self.manager._active_round_number.reset(round_token)

                    tasks.append(_run_agent())

                results = await asyncio.gather(*tasks, return_exceptions=True)

                round_turns: List[AgentTurnResult] = []
                for agent, result in zip(round_members, results):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    if isinstance(result, AgentTurnIncompleteError):
                        aborted_turn = result.result
                        await self.manager._report_operational_degraded(
                            team,
                            AuditResult(
                                status=AuditStatus.UNKNOWN,
                                reason=(
                                    "The discussion aborted before content supervision completed."
                                ),
                                operational_status=(OperationalStatus.DEGRADED),
                                operational_reason=(
                                    "A configured member failure policy "
                                    "aborted the discussion: "
                                    f"agent_id={aborted_turn.agent_id}, "
                                    f"error_kind={aborted_turn.error_kind or 'unknown'}."
                                ),
                            ),
                        )
                        raise result
                    if isinstance(result, ATTException):
                        self.manager.logger.error(
                            "Discussion aborted by framework error: %s", result
                        )
                        raise result
                    elif isinstance(result, Exception):
                        self.manager.logger.error(
                            "Agent %s encountered an unclassified member error of type %s.",
                            agent.name,
                            type(result).__name__,
                        )
                        discussion_had_member_errors = True
                        turn = AgentTurnResult(
                            agent_id=agent.agent_id,
                            team_id=team.team_id,
                            discussion_id=self.manager._active_discussion_id.get(),
                            round_number=r,
                            status=AgentTurnStatus.INCOMPLETE,
                            error_kind="member_exception",
                            reason=(
                                f"{type(result).__name__}: member execution "
                                "failed before producing a structured result."
                            ),
                        )
                    else:
                        turn = result.model_copy(update={"round_number": r})
                        if turn.status is AgentTurnStatus.INCOMPLETE:
                            discussion_had_member_errors = True
                    ans = turn.text
                    round_turns.append(turn)
                    last_round_answers[(r, agent.name)] = ans
                    dialog_history.append(f"{agent.name}: {ans}")

                structured_rounds.append(DiscussionRoundResult(round_number=r, turns=round_turns))

                if self.manager.config.enable_membership_voting:
                    await self.manager._apply_deferred_membership_changes(team)

            transcript = "\n".join(dialog_history)

            if require_complete and discussion_had_member_errors:
                raise RuntimeError(
                    "The governance discussion was incomplete because at "
                    "least one Agent reasoning step failed."
                )

            audit_result, discussion_had_member_errors = await audit_discussion(
                self.manager,
                team,
                transcript,
                structured_rounds,
                skip_audit,
            )
            emit_discussion_log(
                self.manager,
                team,
                prompt,
                rounds,
                transcript,
                audit_result,
            )

            # A governance ballot may only follow a discussion that reached
            # the complete session boundary. A partial member failure keeps
            # every queued communication Approval pending for a later retry.
            if processed_communication_request_ids and not discussion_had_member_errors:
                await self.manager.broker.process_team_approvals_from_transcript(
                    team,
                    sorted(processed_communication_request_ids),
                    transcript,
                    communication_member_snapshot,
                )

            self.manager._auto_save(
                agents={agent.agent_id for agent in team.members},
                teams={team.team_id},
            )
            discussion_succeeded = True
            return DiscussionResult(
                team_id=team.team_id,
                discussion_id=self.manager._active_discussion_id.get(),
                status=(
                    DiscussionStatus.PARTIAL
                    if discussion_had_member_errors
                    else DiscussionStatus.COMPLETED
                ),
                transcript=transcript,
                rounds=structured_rounds,
                audit=audit_result,
            )
        finally:
            await finalize_discussion_session(
                self.manager,
                team,
                processed_peer_message_ids,
                processed_unknown_fingerprints,
                processed_operational_fingerprints,
                discussion_succeeded,
                auto_save_context,
                discussion_token,
            )
