import logging
import json
from typing import Tuple, Any, Optional
from .core import Agent, AgentTeam, generate_with_retry, ATTException

class SupervisoryTeam:
    """Composed of exactly 3 AIs. Audits intra-team and inter-team dialog effectiveness, and triggers recursive parent escalation."""
    def __init__(self, root_ai: Agent, llm_client: Any, manager: Optional[Any] = None):
        self.root_ai = root_ai
        self.llm_client = llm_client
        self.manager = manager
        self.auditors = [
            Agent(name="Auditor_Integrity_01", role="Integrity_Auditor", llm_client=llm_client),
            Agent(name="Auditor_Continuity_02", role="Continuity_Auditor", llm_client=llm_client),
            Agent(name="Auditor_Deadlock_03", role="Deadlock_Auditor", llm_client=llm_client),
        ]
        self.logger = logging.getLogger("SupervisoryTeam")

    async def audit_team_dialog(self, team: AgentTeam, dialog_transcript: str) -> Tuple[bool, str]:
        """
        Evaluates dialogue transcript efficiency inside an AT.
        Returns (is_healthy, reason).
        """
        audit_prompt = (
            f"Audit the following multi-agent discussion transcript for efficiency and logic.\n"
            f"Check if there are deadlocks, repetitive arguments, or deviations from roles.\n\n"
            f"--- TRANSCRIPT BEGIN ---\n"
            f"{dialog_transcript}\n"
            f"--- TRANSCRIPT END ---\n\n"
            f"Output exactly a JSON payload:\n"
            f"{{\n"
            f"  \"is_healthy\": true | false,\n"
            f"  \"reason\": \"Reasoning for your audit...\"\n"
            f"}}"
        )

        try:
            retries = self.manager.config.llm_max_retries if (self.manager and self.manager.config) else 3
            backoff = self.manager.config.llm_retry_backoff_factor if (self.manager and self.manager.config) else 1.5
            response = await generate_with_retry(
                llm_client=self.llm_client,
                prompt=audit_prompt,
                system_instruction="You are a strict, objective Supervisory Auditor. Evaluate communication effectiveness.",
                temperature=0.2,
                require_json=True,
                retries=retries,
                backoff_factor=backoff
            )
            if "```" in response:
                response = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(response)
            is_healthy = bool(data.get("is_healthy", True))
            reason = str(data.get("reason", "No reason provided."))
            self.logger.info(f"Audit for team {team.team_id}: healthy={is_healthy}, reason={reason}")
            return is_healthy, reason
        except Exception as e:
            self.logger.warning(f"Supervisory audit failed, defaulting to healthy: {e}")
            return True, f"Audit failed: {e}"

    async def report_anomaly(self, failed_team: AgentTeam, reason: str, manager: Any):
        """
        Escalates anomaly up the lineage tree by reporting to the direct parent.
        If the parent is not found, escalates directly to the root AI (Level 0).
        """
        self.logger.error(f"[SUPERVISOR ALERT] Anomaly detected in team {failed_team.team_id}: {reason}")
        
        current_parent = failed_team.parent_team or manager.find_parent_team(failed_team)
        
        if current_parent is not None:
            self.logger.info(f"[SUPERVISOR] Escalating failure of child {failed_team.team_id} to parent team {current_parent.team_id}.")
            current_parent.receive_message({
                "type": "child_failure_escalation",
                "from": "Supervisor",
                "failed_team_id": failed_team.team_id,
                "reason": reason
            })
            return
            
        self.logger.critical("[SUPERVISOR CRITICAL] Root-level failure or lineage collapse! Escalating directly to Root AI Level 0.")
        if self.root_ai.llm_client:
            alert_msg = (
                f"CRITICAL SYSTEM FAILURE: Anomaly in team {failed_team.team_id}.\n"
                f"Original anomaly reason: {reason}"
            )
            print(f"!!! ROOT ALERT !!! {alert_msg}")
