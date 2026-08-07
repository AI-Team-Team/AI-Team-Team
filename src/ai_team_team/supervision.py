import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from .core import Agent, generate_with_retry


class AuditStatus(str, Enum):
    """The outcome category of a supervisory audit."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AuditResult:
    """A structured audit result that preserves operational failures."""

    status: AuditStatus
    reason: str
    cause: Optional[str] = None


class SupervisoryTeam:
    """A three-agent committee that audits team discussions."""

    def __init__(
        self,
        root_ai: Agent,
        llm_client: Any,
        manager: Optional[Any] = None,
    ):
        self.root_ai = root_ai
        self.llm_client = llm_client
        self.manager = manager
        self.auditors = [
            Agent(
                name="Auditor_Integrity_01",
                role="Integrity_Auditor",
                llm_client=llm_client,
            ),
            Agent(
                name="Auditor_Continuity_02",
                role="Continuity_Auditor",
                llm_client=llm_client,
            ),
            Agent(
                name="Auditor_Deadlock_03",
                role="Deadlock_Auditor",
                llm_client=llm_client,
            ),
        ]
        self.logger = logging.getLogger("SupervisoryTeam")

    async def _compress_transcript(
        self, transcript: str, llm_client: Any
    ) -> str:
        if len(transcript) < 8000:
            return transcript

        self.logger.info(
            "Transcript is %s characters; compressing it before audit.",
            len(transcript),
        )
        summarize_prompt = (
            "Summarize the following multi-agent conversation transcript "
            "into a dense historical outline. Preserve arguments, logic "
            "shifts, role violations, and deadlock indicators:\n\n"
            f"--- TRANSCRIPT BEGIN ---\n{transcript}\n"
            "--- TRANSCRIPT END ---\n"
        )
        retries = (
            self.manager.config.llm_max_retries
            if self.manager and self.manager.config
            else 3
        )
        backoff = (
            self.manager.config.llm_retry_backoff_factor
            if self.manager and self.manager.config
            else 1.5
        )
        return await generate_with_retry(
            llm_client=llm_client,
            prompt=summarize_prompt,
            system_instruction=(
                "You are a precise context compression assistant."
            ),
            temperature=0.1,
            retries=retries,
            backoff_factor=backoff,
            manager=self.manager,
        )

    async def audit_team_dialog(
        self, team: Any, dialog_transcript: str
    ) -> AuditResult:
        """Audits a transcript without treating audit outages as healthy."""
        for auditor in self.auditors:
            auditor.messages.clear()
        try:
            working_transcript = await self._compress_transcript(
                dialog_transcript, self.llm_client
            )
            from ai_team_team.core.team import AgentTeam

            supervisor_team = AgentTeam(
                creator=self.root_ai,
                preset_name="supervisor_audit",
                team_purpose=(
                    "Audit descendant team dialogues for deadlocks, role "
                    "violations, and reasoning continuity."
                ),
            )
            supervisor_team.members = self.auditors
            supervisor_team.system_instructions = (
                "You are a strict, objective Supervisory Auditor. Cooperate "
                "to evaluate debate logic, deadlocks, and role alignment."
            )
            if self.manager:
                supervisor_team.chapter_num = team.chapter_num

            audit_prompt = (
                "Audit the following multi-agent discussion transcript for "
                "efficiency and logic. Check for deadlocks, repetition, and "
                "role deviation. Debate its health from the perspectives of "
                "integrity, continuity, and deadlock tracking.\n\n"
                f"--- TARGET TRANSCRIPT BEGIN ---\n{working_transcript}\n"
                "--- TARGET TRANSCRIPT END ---\n"
            )
            debate_transcript = await self.manager.execute_team_discussion(
                supervisor_team,
                prompt=audit_prompt,
                rounds=2,
                skip_audit=True,
            )
            consensus_prompt = (
                "Extract the supervisory committee's consensus from the "
                "following debate. Output exactly a JSON object with a "
                "boolean `is_healthy` and string `reason`.\n\n"
                f"{debate_transcript}"
            )
            retries = (
                self.manager.config.llm_max_retries
                if self.manager and self.manager.config
                else 3
            )
            backoff = (
                self.manager.config.llm_retry_backoff_factor
                if self.manager and self.manager.config
                else 1.5
            )
            response = await generate_with_retry(
                llm_client=self.llm_client,
                prompt=consensus_prompt,
                system_instruction=(
                    "You are a precise JSON consensus synthesis compiler."
                ),
                temperature=0.2,
                require_json=True,
                retries=retries,
                backoff_factor=backoff,
                manager=self.manager,
            )
            if not isinstance(response, str):
                response = getattr(response, "text", response)
            if not isinstance(response, str):
                raise TypeError("Audit consensus response must be text.")
            if "```" in response:
                response = (
                    response.replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
            data = json.loads(response)
            if type(data.get("is_healthy")) is not bool:
                raise ValueError(
                    "Audit consensus must contain boolean `is_healthy`."
                )
            reason = data.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(
                    "Audit consensus must contain a non-empty `reason`."
                )
            status = (
                AuditStatus.HEALTHY
                if data["is_healthy"]
                else AuditStatus.UNHEALTHY
            )
            result = AuditResult(status=status, reason=reason)
            self.logger.info(
                "Consensus audit for team %s: status=%s, reason=%s",
                team.team_id,
                result.status.value,
                result.reason,
            )
            return result
        except Exception as exc:
            self.logger.error(
                "Supervisory audit could not determine a result: %s", exc
            )
            return AuditResult(
                status=AuditStatus.UNKNOWN,
                reason="The supervisory audit service could not determine "
                "the discussion's health.",
                cause=f"{type(exc).__name__}: {exc}",
            )

    async def report_anomaly(
        self, failed_team: Any, reason: str, manager: Any
    ) -> None:
        """Escalates a confirmed anomaly to the parent or root callbacks."""
        await self._report(
            failed_team=failed_team,
            manager=manager,
            message_type="child_failure_escalation",
            reason=reason,
            cause=None,
        )

    async def report_unknown(
        self, failed_team: Any, result: AuditResult, manager: Any
    ) -> None:
        """Escalates an indeterminate audit according to manager policy."""
        await self._report(
            failed_team=failed_team,
            manager=manager,
            message_type="audit_unknown_escalation",
            reason=result.reason,
            cause=result.cause,
        )

    async def _report(
        self,
        *,
        failed_team: Any,
        manager: Any,
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

        current_parent = (
            failed_team.parent_team
            or manager.find_parent_team(failed_team)
        )
        if current_parent is not None:
            current_parent.receive_message(message)
            return

        self.logger.critical(
            "Root-level supervisory escalation for team %s: %s",
            failed_team.team_id,
            reason,
        )
        manager._emit_callback(
            "on_system_event", message_type, dict(message)
        )
        manager._emit_callback(
            "on_emergency_escalation",
            failed_team.team_id,
            message_type,
            reason,
        )
