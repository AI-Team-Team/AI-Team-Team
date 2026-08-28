"""Inbox claim and prompt-context preparation for discussion sessions."""

from typing import Any, Set

from ...utils import generate_with_retry


async def prepare_inbox_context(
    manager: Any,
    team: Any,
    processed_unknown_fingerprints: Set[str],
    processed_operational_fingerprints: Set[str],
    processed_communication_request_ids: Set[str],
    processed_peer_message_ids: Set[str],
) -> str:
    """Claim pending inbox work and render its discussion prompt context."""
    with team.inbox_lock:
        pending_inbox = []
        retained_inbox = []
        for message in team.message_inbox:
            message_type = message.get("type")
            if message_type == "audit_unknown_escalation":
                if message.get("state", "pending") == "pending":
                    message["state"] = "processing"
                    message["processing_count"] = message.get("occurrence_count", 1)
                    pending_inbox.append(message)
                    processed_unknown_fingerprints.add(message["fingerprint"])
                retained_inbox.append(message)
            elif message_type == "operational_degraded_escalation":
                if message.get("state", "pending") == "pending":
                    message["state"] = "processing"
                    message["processing_count"] = message.get("occurrence_count", 1)
                    pending_inbox.append(message)
                    processed_operational_fingerprints.add(message["fingerprint"])
                retained_inbox.append(message)
            elif message_type == "communication_approval_request":
                request_id = message.get("request_id")
                if request_id:
                    pending_inbox.append(message)
                    processed_communication_request_ids.add(request_id)
                retained_inbox.append(message)
            elif message_type == "peer_message":
                message_id = message.get("message_id")
                pending_inbox.append(message)
                retained_inbox.append(message)
                if message_id:
                    processed_peer_message_ids.add(message_id)
            else:
                pending_inbox.append(message)
        team.message_inbox = retained_inbox

    if not pending_inbox:
        return ""
    inbox_lines = [
        f"- **From [{msg.get('from', 'Unknown')}]**: "
        f"{msg.get('reason') or msg.get('objective') or str(msg)}"
        for msg in pending_inbox
    ]
    raw_inbox_text = "\n".join(inbox_lines)
    threshold = manager.config.inbox_summarize_threshold_chars
    if len(raw_inbox_text) > threshold:
        raw_inbox_text = await _summarize_inbox(manager, team, raw_inbox_text)
    manager._auto_save(inboxes={team.team_id})
    return (
        "\n\n### UNRESOLVED INBOX ALERTS & ESCALATIONS\n"
        "Your team has received the following signals from your descendants "
        "or supervisor:\n"
        f"{raw_inbox_text}\n"
        "Please address or incorporate these alerts into your decision-making."
    )


async def _summarize_inbox(manager: Any, team: Any, text: str) -> str:
    summarize_client = None
    if team.members and getattr(team.members[0], "llm_client", None):
        summarize_client = team.members[0].llm_client
    elif manager.root_ai and getattr(manager.root_ai, "llm_client", None):
        summarize_client = manager.root_ai.llm_client
    if not summarize_client:
        return text
    manager.logger.info("Inbox context too large, summarizing before injection...")
    try:
        return await generate_with_retry(
            llm_client=summarize_client,
            prompt=(f"Summarize the following system alerts and escalations concisely:\n\n{text}"),
            system_instruction=(
                "You are a strict system summarizer. Compress alerts while "
                "keeping critical facts and failures."
            ),
            temperature=0.1,
            retries=manager.config.llm_max_retries,
            backoff_factor=manager.config.llm_retry_backoff_factor,
            manager=manager,
        )
    except Exception as exc:
        manager.logger.warning("Failed to summarize inbox: %s", exc)
        return text
