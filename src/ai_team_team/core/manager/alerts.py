"""Durable operational alerts and emergency wakeup scheduling."""

import asyncio
import hashlib
import json
import queue
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..manager import ATTManager
    from ..team import AgentTeam


class AlertService:
    """Owns alert coalescing, acknowledgement, and wakeup deduplication."""

    DURABLE_TYPES = {
        "audit_unknown_escalation",
        "operational_degraded_escalation",
    }

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.active_wakeups: set[str] = set()
        self.emergency_tasks: set[asyncio.Task[Any]] = set()
        self.deferred_emergency_tasks: queue.Queue[Any] = queue.Queue()

    async def flush_deferred_tasks(self) -> None:
        while not self.deferred_emergency_tasks.empty():
            team, alert, skip_audit = self.deferred_emergency_tasks.get_nowait()
            self.schedule_emergency_wakeup(team, alert, skip_audit=skip_audit)

    def schedule_emergency_wakeup(
        self,
        team: "AgentTeam",
        alert: Dict[str, Any],
        *,
        skip_audit: bool = False,
    ) -> None:
        if self.manager._closing:
            return
        dedupe_key = None
        if alert.get("type") in self.DURABLE_TYPES:
            dedupe_key = self.wakeup_key(team, alert)
            if dedupe_key in self.active_wakeups:
                return
            self.active_wakeups.add(dedupe_key)

        async def run() -> None:
            try:
                await self.manager.execute_emergency_discussion(team, alert, skip_audit=skip_audit)
            finally:
                if dedupe_key is not None:
                    self.active_wakeups.discard(dedupe_key)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if dedupe_key is not None:
                self.active_wakeups.discard(dedupe_key)
            self.deferred_emergency_tasks.put_nowait((team, dict(alert), skip_audit))
            self.manager.logger.info(
                "Queued emergency wakeup for team %s until an event loop is available.",
                team.team_id,
            )
        else:
            task = loop.create_task(run())
            self.emergency_tasks.add(task)
            task.add_done_callback(self.emergency_tasks.discard)

    @staticmethod
    def fingerprint(alert: Dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "type": alert.get("type"),
                "failed_team_id": alert.get("failed_team_id"),
                "reason": alert.get("reason"),
                "cause": alert.get("cause"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def merge(self, team: "AgentTeam", alert: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        alert_type = alert.get("type")
        if alert_type not in self.DURABLE_TYPES:
            raise ValueError("Unsupported durable alert type.")
        fingerprint = alert.get("fingerprint") or self.fingerprint(alert)
        with team.inbox_lock:
            existing = next(
                (
                    item
                    for item in team.message_inbox
                    if item.get("type") == alert_type and item.get("fingerprint") == fingerprint
                ),
                None,
            )
            if existing is not None:
                existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
                existing["last_seen"] = now
                merged = existing
            else:
                merged = dict(alert)
                merged.update(
                    {
                        "fingerprint": fingerprint,
                        "occurrence_count": 1,
                        "first_seen": now,
                        "last_seen": now,
                        "state": "pending",
                    }
                )
                team.message_inbox.append(merged)
            unique_count = sum(item.get("type") == alert_type for item in team.message_inbox)
        if unique_count >= self.manager.config.audit_unknown_soft_threshold:
            event_name = (
                "audit_unknown_soft_threshold"
                if alert_type == "audit_unknown_escalation"
                else "operational_degraded_soft_threshold"
            )
            self.manager.logger.warning(
                "Team %s has %s unique pending %s alerts.",
                team.team_id,
                unique_count,
                alert_type,
            )
            self.manager._emit_callback(
                "on_system_event",
                event_name,
                {
                    "team_id": team.team_id,
                    "alert_type": alert_type,
                    "unique_alerts": unique_count,
                },
            )
        return merged

    def finish_processing(
        self,
        team: "AgentTeam",
        alert_type: str,
        fingerprints: set[str],
        succeeded: bool,
    ) -> None:
        with team.inbox_lock:
            retained = []
            for message in team.message_inbox:
                selected = (
                    message.get("type") == alert_type and message.get("fingerprint") in fingerprints
                )
                if not selected:
                    retained.append(message)
                    continue
                processing_count = message.pop(
                    "processing_count", message.get("occurrence_count", 1)
                )
                if not succeeded or message.get("occurrence_count", 1) > processing_count:
                    message["state"] = "pending"
                    retained.append(message)
            team.message_inbox = retained
        self.manager._auto_save(inboxes={team.team_id})

    async def report_operational_degraded(self, team: "AgentTeam", audit_result: Any) -> None:
        message = {
            "type": "operational_degraded_escalation",
            "from": "Supervisor",
            "failed_team_id": team.team_id,
            "reason": audit_result.operational_reason,
        }
        message["fingerprint"] = self.fingerprint(message)
        self.manager._emit_callback("on_system_event", "operational_degraded", dict(message))
        mode = self.manager.config.operational_degraded_escalation_mode
        if mode == "none":
            return
        parent = team.parent_team or self.manager.find_parent_team(team)
        if parent is None:
            self.manager._emit_callback(
                "on_emergency_escalation",
                team.team_id,
                message["type"],
                message["reason"],
            )
            return
        parent.receive_message(message)

    def acknowledge(self, team_id: str, fingerprint: str) -> bool:
        team = self._require_team(team_id)
        with team.inbox_lock:
            before = len(team.message_inbox)
            team.message_inbox = [
                item
                for item in team.message_inbox
                if not (
                    item.get("type") == "audit_unknown_escalation"
                    and item.get("fingerprint") == fingerprint
                )
            ]
            changed = len(team.message_inbox) != before
        if changed:
            self.manager._auto_save(inboxes={team_id})
        return changed

    def clear(self, team_id: str, fingerprints: Optional[set[str]] = None) -> int:
        team = self._require_team(team_id)
        with team.inbox_lock:
            retained = []
            removed = 0
            for item in team.message_inbox:
                is_unknown = item.get("type") == "audit_unknown_escalation"
                selected = fingerprints is None or item.get("fingerprint") in fingerprints
                if is_unknown and selected:
                    removed += 1
                else:
                    retained.append(item)
            team.message_inbox = retained
        if removed:
            self.manager._auto_save(inboxes={team_id})
        return removed

    def wakeup_key(self, team: "AgentTeam", alert: Dict[str, Any]) -> str:
        fingerprint = alert.get("fingerprint") or self.fingerprint(alert)
        return f"{team.team_id}:{alert.get('type')}:{fingerprint}"

    def is_wakeup_active(self, team: "AgentTeam", alert: Dict[str, Any]) -> bool:
        return self.wakeup_key(team, alert) in self.active_wakeups

    def _require_team(self, team_id: str) -> "AgentTeam":
        team = self.manager.teams.get(team_id)
        if team is None:
            raise KeyError(f"Unknown team {team_id!r}.")
        return team
