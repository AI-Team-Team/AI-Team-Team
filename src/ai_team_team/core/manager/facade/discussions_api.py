"""Public ATTManager delegation methods for DiscussionAPI."""

from typing import TYPE_CHECKING, Any, Dict, Optional


from ...team import AgentTeam
from ..alerts import AlertService

if TYPE_CHECKING:
    from ...response import DiscussionResult


class DiscussionAPI:
    async def execute_team_discussion(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> str:
        """Queues one discussion behind this AgentTeam's active session."""
        return await self._discussion.execute_team_discussion(team, prompt, rounds, skip_audit)

    async def execute_team_discussion_detailed(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> "DiscussionResult":
        """Runs one serialized discussion and returns structured turns."""
        return await self._discussion.execute_team_discussion_detailed(
            team, prompt, rounds, skip_audit
        )

    async def _execute_team_discussion_with_members(self, *args: Any, **kwargs: Any) -> Any:
        return await self._discussion._execute_team_discussion_with_members(*args, **kwargs)

    async def _execute_team_discussion_session(self, *args: Any, **kwargs: Any) -> Any:
        return await self._discussion._execute_team_discussion_session(*args, **kwargs)

    async def flush_deferred_tasks(self) -> None:
        """Schedules deferred emergency call specifications."""
        await self._alerts.flush_deferred_tasks()

    def schedule_emergency_wakeup(
        self,
        team: AgentTeam,
        alert: Dict[str, Any],
        *,
        skip_audit: bool = False,
    ) -> None:
        """Schedules an emergency discussion with stable deduplication."""
        self._alerts.schedule_emergency_wakeup(team, alert, skip_audit=skip_audit)

    @staticmethod
    def _unknown_alert_fingerprint(alert: Dict[str, Any]) -> str:
        return AlertService.fingerprint(alert)

    def _merge_unknown_alert(self, team: AgentTeam, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility wrapper for UNKNOWN audit alerts."""
        return self._alerts.merge(team, alert)

    def _merge_durable_alert(self, team: AgentTeam, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Persistently coalesces one operational alert."""
        return self._alerts.merge(team, alert)

    def _finish_durable_alert_processing(self, *args: Any, **kwargs: Any) -> Any:
        return self._alerts.finish_processing(*args, **kwargs)

    async def _report_operational_degraded(self, team: AgentTeam, audit_result: Any) -> None:
        await self._alerts.report_operational_degraded(team, audit_result)

    def acknowledge_unknown_alert(self, team_id: str, fingerprint: str) -> bool:
        """Explicitly acknowledges and removes one UNKNOWN alert."""
        return self._alerts.acknowledge(team_id, fingerprint)

    def clear_unknown_alerts(self, team_id: str, fingerprints: Optional[set[str]] = None) -> int:
        """Explicitly clears selected or all UNKNOWN alerts for one team."""
        return self._alerts.clear(team_id, fingerprints)

    @staticmethod
    def _unknown_audit_wakeup_key(team: AgentTeam, alert: Dict[str, Any]) -> str:
        fingerprint = alert.get("fingerprint") or AlertService.fingerprint(alert)
        return f"{team.team_id}:{alert.get('type')}:{fingerprint}"

    def is_unknown_audit_wakeup_active(self, team: AgentTeam, alert: Dict[str, Any]) -> bool:
        """Returns whether an identical UNKNOWN wakeup is already active."""
        return self._alerts.is_wakeup_active(team, alert)

    async def execute_emergency_discussion(
        self,
        team: AgentTeam,
        alert: Dict[str, Any],
        *,
        skip_audit: bool = False,
    ) -> str:
        """Executes an emergency discussion round to handle child failure or escalation."""
        emergency_prompt = (
            f"EMERGENCY MEETING: An anomaly or escalation was reported from your child team or supervisor.\n"
            f"Alert details: {alert.get('reason') or alert.get('objective') or str(alert)}\n"
            f"Please evaluate this issue and decide on corrective actions or escalate further."
        )
        rounds = getattr(self.config, "emergency_discussion_rounds", 1)
        self.logger.warning(
            f"Starting emergency discussion on team {team.team_id} for {rounds} round(s)..."
        )
        return await self.execute_team_discussion(
            team,
            prompt=emergency_prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
