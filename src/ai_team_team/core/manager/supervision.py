"""Audit-scoped supervisory AgentTeam orchestration."""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional

from ..exceptions import StatePersistenceError
from ..response import AuditResult, AuditStatus, OperationalStatus
from ..utils import generate_with_retry

if TYPE_CHECKING:
    from ..agent import Agent
    from ..team import AgentTeam
    from .facade import ATTManager


class SupervisionService:
    """Runs each audit through a newly registered, short-lived AgentTeam."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.logger = logging.getLogger("ATTManager.Supervision")
        self.active_tasks: set[asyncio.Task[Any]] = set()
        self.finalizers: set[asyncio.Task[Any]] = set()

    def is_supervisory_agent(self, agent_id: str) -> bool:
        """Exclude audit-scoped identities from ordinary team recruitment."""
        return any(
            team.team_kind == "supervisory"
            and any(member.agent_id == agent_id for member in team.members)
            for team in self.manager.teams.values()
        )

    async def _member_generate(
        self,
        team: "AgentTeam",
        agent: "Agent",
        prompt: str,
        system_instruction: str,
        *,
        require_json: bool = False,
        temperature: float = 0.2,
    ) -> str:
        """Run an attributed model step under the normal Agent invocation guard."""
        manager = self.manager
        if manager.teams.get(team.team_id) is not team or agent not in team.members:
            raise RuntimeError("The supervisory model step has no registered team member.")
        async with manager.agent_invocation(agent):
            team_token = manager._active_team.set(team)
            discussion_id = manager._active_discussion_id.get() or f"DISC-{uuid.uuid4().hex}"
            discussion_token = manager._active_discussion_id.set(discussion_id)
            try:
                agent.append_message(
                    {
                        "role": "user",
                        "content": prompt,
                        "team_id": team.team_id,
                        "discussion_id": discussion_id,
                    }
                )
                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    require_json=require_json,
                    retries=manager.config.llm_max_retries,
                    backoff_factor=manager.config.llm_retry_backoff_factor,
                    manager=manager,
                )
                text = response if isinstance(response, str) else getattr(response, "text", None)
                if not isinstance(text, str):
                    raise TypeError("Supervisory model response must be text.")
                agent.append_message(
                    {
                        "role": "assistant",
                        "content": text,
                        "team_id": team.team_id,
                        "discussion_id": discussion_id,
                    }
                )
                return text
            finally:
                manager._auto_save(agents={agent.agent_id})
                manager._active_discussion_id.reset(discussion_token)
                manager._active_team.reset(team_token)

    async def _compress_transcript(self, team: "AgentTeam", transcript: str) -> str:
        if len(transcript) < 8000:
            return transcript
        return await self._member_generate(
            team,
            team.members[0],
            "Summarize the following multi-agent conversation transcript "
            "for the supervisory audit. Preserve arguments, reasoning changes, "
            "role violations, and deadlocks.\n\n"
            f"--- TRANSCRIPT BEGIN ---\n{transcript}\n--- TRANSCRIPT END ---",
            "You are a precise audit-context compression assistant.",
            temperature=0.1,
        )

    def _parse_consensus(
        self,
        response: str,
        operational_status: OperationalStatus,
        operational_reason: str,
    ) -> AuditResult:
        cleaned = response.strip()
        if cleaned.startswith("```json") and cleaned.endswith("```"):
            cleaned = cleaned[7:-3].strip()
        elif cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict) or type(data.get("is_healthy")) is not bool:
            raise ValueError("Audit consensus must contain boolean `is_healthy`.")
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Audit consensus must contain a non-empty `reason`.")
        decision_mode = self.manager.config.operational_status_decision_mode
        if decision_mode in {"supervisor", "framework_then_supervisor"}:
            try:
                operational_status = OperationalStatus(data.get("operational_status"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Audit consensus must contain operational_status as healthy or degraded."
                ) from exc
            operational_reason = data.get("operational_reason")
            if not isinstance(operational_reason, str) or not operational_reason.strip():
                raise ValueError("Audit consensus must contain a non-empty operational_reason.")
        return AuditResult(
            status=AuditStatus.HEALTHY if data["is_healthy"] else AuditStatus.UNHEALTHY,
            reason=reason,
            operational_status=operational_status,
            operational_reason=operational_reason,
        )

    def _unknown_result(
        self,
        error: BaseException,
        operational_status: OperationalStatus,
        operational_reason: str,
    ) -> AuditResult:
        decision_mode = self.manager.config.operational_status_decision_mode
        if decision_mode == "supervisor":
            operational_status = OperationalStatus.UNKNOWN
            operational_reason = "The supervisor could not determine runtime health."
        return AuditResult(
            status=AuditStatus.UNKNOWN,
            reason="The supervisory audit service could not determine the discussion's health.",
            cause=f"{type(error).__name__}: {error}",
            operational_status=operational_status,
            operational_reason=operational_reason,
        )

    async def _finish_audit(
        self,
        audit_id: str,
        target_team: "AgentTeam",
        supervisory_team: "AgentTeam",
        source_transcript: str,
        debate_transcript: str,
        result: AuditResult,
        *,
        cancelled: bool,
    ) -> None:
        manager = self.manager
        event = None
        evidence_committed = False
        try:
            event = manager._memory.record_event(
                "supervisory_audit_completed",
                team=supervisory_team,
                payload={
                    "audit_id": audit_id,
                    "target_team_id": target_team.team_id,
                    "supervisory_team_id": supervisory_team.team_id,
                    "auditor_agent_ids": [agent.agent_id for agent in supervisory_team.members],
                    "source_sha256": hashlib.sha256(source_transcript.encode("utf-8")).hexdigest(),
                    "source_transcript": source_transcript,
                    "debate_transcript": debate_transcript,
                    "result": result.model_dump(mode="json"),
                    "cancelled": cancelled,
                },
                persist=False,
                inherit_context=False,
            )
            dirty = manager._new_dirty_state()
            dirty["memory_events"].add(event.event_id)
            await manager._commit_dirty_state(dirty)
            evidence_committed = True
            await manager._team_creation.dissolve_supervisory_team(supervisory_team)
        except BaseException:
            if event is not None and not evidence_committed:
                manager._memory.discard_unpersisted_event(event.event_id)
            if manager.teams.get(supervisory_team.team_id) is supervisory_team:
                await manager._team_creation.dissolve_supervisory_team(
                    supervisory_team, persist=False
                )
            raise

    async def audit_team_dialog(
        self,
        team: "AgentTeam",
        dialog_transcript: str,
        *,
        operational_status: OperationalStatus = OperationalStatus.HEALTHY,
        operational_reason: str = "All member turns completed.",
    ) -> AuditResult:
        """Audit one discussion with fresh, isolated, managed AgentTeam members."""
        manager = self.manager
        if not isinstance(dialog_transcript, str):
            raise TypeError("The audited discussion transcript must be text.")
        if manager.teams.get(team.team_id) is not team or team.team_kind != "ordinary":
            raise ValueError("Only a registered ordinary AgentTeam can be audited.")
        audit_id = f"AUDIT-{uuid.uuid4().hex}"
        audit_task = asyncio.current_task()
        if audit_task is not None:
            self.active_tasks.add(audit_task)
        batch_token = manager._persistence_batch.set(None)
        supervisory_team: Optional[AgentTeam] = None
        debate_transcript = ""
        result: Optional[AuditResult] = None
        cancelled = False
        try:
            supervisory_team = manager._team_creation.create_supervisory_team()
            try:
                await manager.flush_state()
                working_transcript = await self._compress_transcript(
                    supervisory_team, dialog_transcript
                )
                audit_prompt = (
                    "Audit the following AgentTeam discussion for efficiency and logic. "
                    "Check for deadlocks, repetition, and role deviation. Debate its "
                    "health from your distinct audit roles.\n\n"
                    f"--- TARGET TRANSCRIPT BEGIN ---\n{working_transcript}\n"
                    "--- TARGET TRANSCRIPT END ---\n"
                )
                debate, _members = await manager._execute_team_discussion_with_members(
                    supervisory_team,
                    audit_prompt,
                    rounds=2,
                    skip_audit=True,
                    require_complete=True,
                    process_inbox=False,
                )
                debate_transcript = debate.transcript
                operational_instruction = ""
                if manager.config.operational_status_decision_mode in {
                    "supervisor", "framework_then_supervisor"
                }:
                    operational_instruction = (
                        " Also output `operational_status` as exactly `healthy` or "
                        "`degraded`, plus a non-empty `operational_reason`."
                    )
                consensus_prompt = (
                    "Extract this supervisory AgentTeam's consensus from its debate. "
                    "Output exactly a JSON object with a boolean `is_healthy` "
                    "and string `reason`."
                    f"{operational_instruction}\n\n{debate_transcript}"
                )
                response = await self._member_generate(
                    supervisory_team,
                    supervisory_team.members[0],
                    consensus_prompt,
                    "You are a precise JSON consensus synthesis compiler for your team.",
                    require_json=True,
                )
                result = self._parse_consensus(
                    response, operational_status, operational_reason
                )
            except asyncio.CancelledError as exc:
                cancelled = True
                result = self._unknown_result(exc, operational_status, operational_reason)
            except StatePersistenceError:
                await manager._team_creation.dissolve_supervisory_team(
                    supervisory_team, persist=False
                )
                raise
            except Exception as exc:
                self.logger.error(
                    "Supervisory audit could not determine a result: %s", exc
                )
                result = self._unknown_result(exc, operational_status, operational_reason)
            if result is None:
                raise RuntimeError("The supervisory audit produced no result.")
            finalizer = asyncio.create_task(
                self._finish_audit(
                    audit_id,
                    team,
                    supervisory_team,
                    dialog_transcript,
                    debate_transcript,
                    result,
                    cancelled=cancelled,
                ),
                name=f"att-supervisory-finish-{audit_id}",
            )
            self.finalizers.add(finalizer)
            try:
                while True:
                    try:
                        await asyncio.shield(finalizer)
                        break
                    except asyncio.CancelledError:
                        cancelled = True
                        if finalizer.done():
                            finalizer.result()
                            break
            finally:
                self.finalizers.discard(finalizer)
            if cancelled:
                raise asyncio.CancelledError()
            return result
        finally:
            manager._persistence_batch.reset(batch_token)
            if audit_task is not None:
                self.active_tasks.discard(audit_task)

    async def report_anomaly(
        self, failed_team: "AgentTeam", reason: str, manager: "ATTManager"
    ) -> None:
        await self._report(failed_team, manager, "child_failure_escalation", reason, None)

    async def report_unknown(
        self, failed_team: "AgentTeam", result: AuditResult, manager: "ATTManager"
    ) -> None:
        await self._report(
            failed_team, manager, "audit_unknown_escalation", result.reason, result.cause
        )

    async def _report(
        self,
        failed_team: "AgentTeam",
        manager: "ATTManager",
        message_type: str,
        reason: str,
        cause: Optional[str],
    ) -> None:
        message = {
            "type": message_type,
            "from": "Supervisor",
            "failed_team_id": failed_team.team_id,
            "reason": reason,
        }
        if cause:
            message["cause"] = cause
        parent = failed_team.parent_team or manager.find_parent_team(failed_team)
        if parent is not None:
            parent.receive_message(message)
            return
        self.logger.critical(
            "Root-level supervisory escalation for team %s: %s",
            failed_team.team_id,
            reason,
        )
        manager._emit_callback("on_system_event", message_type, dict(message))
        manager._emit_callback(
            "on_emergency_escalation", failed_team.team_id, message_type, reason
        )
