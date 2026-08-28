"""Reliable finalization of discussion-owned inbox and context state."""

import time
from typing import Any, Set


async def finalize_discussion_session(
    manager: Any,
    team: Any,
    processed_peer_message_ids: Set[str],
    processed_unknown_fingerprints: Set[str],
    processed_operational_fingerprints: Set[str],
    discussion_succeeded: bool,
    auto_save_context: Any,
    discussion_token: Any,
) -> None:
    """Commit or release claimed inbox work and restore session context."""
    try:
        try:
            if processed_peer_message_ids and discussion_succeeded:
                _consume_peer_messages(manager, team, processed_peer_message_ids)
            if processed_unknown_fingerprints:
                _finish_unknown_alerts(
                    manager,
                    team,
                    processed_unknown_fingerprints,
                    discussion_succeeded,
                )
            if processed_operational_fingerprints:
                manager._finish_durable_alert_processing(
                    team,
                    "operational_degraded_escalation",
                    processed_operational_fingerprints,
                    discussion_succeeded,
                )
        finally:
            await auto_save_context.__aexit__(None, None, None)
    finally:
        try:
            manager._active_discussion_id.reset(discussion_token)
        finally:
            team.is_running = False
    _schedule_followup_wakeup(manager, team)


def _consume_peer_messages(manager: Any, team: Any, message_ids: Set[str]) -> None:
    consumed_at = time.time()
    with team.inbox_lock:
        team.message_inbox = [
            message
            for message in team.message_inbox
            if message.get("message_id") not in message_ids
        ]
    changed_peer_messages = set()
    with manager._snapshot_lock:
        for message_id in message_ids:
            message = manager.broker.peer_messages.get(message_id)
            if message is not None:
                message.delivery_state = "consumed"
                message.consumed_at = consumed_at
                changed_peer_messages.add(message_id)
    manager._auto_save(inboxes={team.team_id}, peer_messages=changed_peer_messages)


def _finish_unknown_alerts(
    manager: Any,
    team: Any,
    fingerprints: Set[str],
    discussion_succeeded: bool,
) -> None:
    with team.inbox_lock:
        if discussion_succeeded:
            retained_messages = []
            for message in team.message_inbox:
                is_processed_alert = (
                    message.get("type") == "audit_unknown_escalation"
                    and message.get("fingerprint") in fingerprints
                )
                if not is_processed_alert:
                    retained_messages.append(message)
                    continue
                processing_count = message.pop(
                    "processing_count", message.get("occurrence_count", 1)
                )
                if message.get("occurrence_count", 1) > processing_count:
                    message["state"] = "pending"
                    retained_messages.append(message)
            team.message_inbox = retained_messages
        else:
            for message in team.message_inbox:
                if (
                    message.get("type") == "audit_unknown_escalation"
                    and message.get("fingerprint") in fingerprints
                ):
                    message["state"] = "pending"
                    message.pop("processing_count", None)
    manager._auto_save(inboxes={team.team_id})


def _schedule_followup_wakeup(manager: Any, team: Any) -> None:
    if not team.message_inbox or not manager.config.enable_emergency_wakeup:
        return
    wake_types = {"child_failure_escalation", "escalation_spawn"}
    if manager.config.audit_unknown_escalation_mode == "wake":
        wake_types.add("audit_unknown_escalation")
    if manager.config.operational_degraded_escalation_mode == "wake":
        wake_types.add("operational_degraded_escalation")
    emergency_msg = next(
        (msg for msg in team.message_inbox if msg.get("type") in wake_types),
        None,
    )
    if emergency_msg:
        manager.schedule_emergency_wakeup(
            team,
            emergency_msg,
            skip_audit=(
                emergency_msg.get("type")
                in {
                    "audit_unknown_escalation",
                    "operational_degraded_escalation",
                }
            ),
        )
