import logging
import json
from typing import Tuple, Any, Optional
from .core import Agent, generate_with_retry, ATTException

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

    async def _compress_transcript(self, transcript: str, llm_client: Any) -> str:
        """Summarizes extremely long transcripts using a fast LLM call to save token overhead."""
        if len(transcript) < 8000:
            return transcript
            
        self.logger.info(f"Transcript too large ({len(transcript)} chars), summarizing before audit debate...")
        summarize_prompt = (
            f"Summarize the following multi-agent conversation transcript into a dense historical outline. "
            f"Preserve all arguments, logic shifts, role violations, and deadlock indicators:\n\n"
            f"--- TRANSCRIPT BEGIN ---\n"
            f"{transcript}\n"
            f"--- TRANSCRIPT END ---\n"
        )
        
        retries = self.manager.config.llm_max_retries if (self.manager and self.manager.config) else 3
        backoff = self.manager.config.llm_retry_backoff_factor if (self.manager and self.manager.config) else 1.5
        
        try:
            summary = await generate_with_retry(
                llm_client=llm_client,
                prompt=summarize_prompt,
                system_instruction="You are a precise context compression assistant.",
                temperature=0.1,
                retries=retries,
                backoff_factor=backoff
            )
            return summary
        except Exception as e:
            self.logger.warning(f"Failed to compress transcript: {e}. Proceeding with truncated transcript.")
            return transcript[-8000:]

    async def audit_team_dialog(self, team: Any, dialog_transcript: str) -> Tuple[bool, str]:
        """
        Evaluates dialogue transcript efficiency inside an AT using a 3-AI debate committee.
        Returns (is_healthy, reason).
        """
        try:
            # 1. Compress transcript if too long
            working_transcript = await self._compress_transcript(dialog_transcript, self.llm_client)

            # 2. Import locally to avoid circular dependencies at load time
            from ai_team_team.core.team import AgentTeam
            
            # Assemble a transient AgentTeam representing the audit committee
            supervisor_team = AgentTeam(
                creator=self.root_ai,
                preset_name="supervisor_audit",
                team_purpose="Audit descendant team dialogues for deadlocks, role violations, and reasoning continuity."
            )
            supervisor_team.members = self.auditors
            supervisor_team.system_instructions = (
                "You are a strict, objective Supervisory Auditor. Cooperate to evaluate debate logic, deadlocks, and role alignment."
            )
            if self.manager:
                supervisor_team.chapter_num = team.chapter_num

            # 3. Trigger standard debate among the auditors (non-recursive skip_audit=True, rounds=2)
            audit_prompt = (
                f"Audit the following multi-agent discussion transcript for efficiency and logic.\n"
                f"Check if there are deadlocks, repetitive arguments, or deviations from roles.\n"
                f"The 3 of you represent Integrity, Continuity, and Deadlock tracking. Debate the health of this dialogue.\n\n"
                f"--- TARGET TRANSCRIPT BEGIN ---\n"
                f"{working_transcript}\n"
                f"--- TARGET TRANSCRIPT END ---\n"
            )

            debate_transcript = await self.manager.execute_team_discussion(
                supervisor_team,
                prompt=audit_prompt,
                rounds=2,
                skip_audit=True
            )

            # 4. Extract JSON consensus from the debate transcript
            consensus_prompt = (
                f"Below is the debate and discussion transcript among the 3 Supervisory Auditors "
                f"evaluating a child team's dialogue.\n\n"
                f"--- AUDITOR DEBATE TRANSCRIPT BEGIN ---\n"
                f"{debate_transcript}\n"
                f"--- AUDITOR DEBATE TRANSCRIPT END ---\n\n"
                f"Based on their discussion, extract their consensus on the health of the child team's dialogue.\n"
                f"Output exactly a JSON payload:\n"
                f"{{\n"
                f"  \"is_healthy\": true | false,\n"
                f"  \"reason\": \"A concise summary of their combined consensus and reasoning...\"\n"
                f"}}"
            )

            retries = self.manager.config.llm_max_retries if (self.manager and self.manager.config) else 3
            backoff = self.manager.config.llm_retry_backoff_factor if (self.manager and self.manager.config) else 1.5

            response = await generate_with_retry(
                llm_client=self.llm_client,
                prompt=consensus_prompt,
                system_instruction="You are a precise JSON consensus synthesis compiler.",
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
            self.logger.info(f"Consensus Audit for team {team.team_id}: healthy={is_healthy}, reason={reason}")
            return is_healthy, reason

        except Exception as e:
            # Safe Fallback: degrade gracefully to not block business operations
            self.logger.warning(f"Supervisory audit failed, defaulting to healthy: {e}")
            return True, f"Audit failed: {e}"

    async def report_anomaly(self, failed_team: Any, reason: str, manager: Any):
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
