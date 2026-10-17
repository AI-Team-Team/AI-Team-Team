"""Canonical immutable Journal values and read-only restore compatibility."""

import json

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import SystemMemoryEventModel


def event_values(event):
    """Use the same persisted representation for validation and writing."""
    return {
        "event_id": event["event_id"],
        "sequence": event["sequence"],
        "event_type": event["event_type"],
        "agent_id": event.get("agent_id"),
        "agent_name_snapshot": event.get("agent_name_snapshot"),
        "team_id": event.get("team_id"),
        "invocation_id": event.get("invocation_id"),
        "source_chat_message_id": event.get("source_chat_message_id"),
        "source_execution_id": event.get("source_execution_id"),
        "checkpoint_context": {key: event.get(key) for key in ("discussion_id", "turn_id")},
        "role": event.get("role"),
        "payload": event.get("payload", {}),
        "redacted": int(event.get("redacted", False)),
        "created_at": event["created_at"],
    }


def event_matches(existing, values):
    """Compare JSON contents without Python's boolean/number equality aliases."""
    for key, value in values.items():
        current = getattr(existing, key)
        if key in {"payload", "checkpoint_context"}:
            # Object order is insignificant, but array order and JSON values are not.
            if json.dumps(current, sort_keys=True) != json.dumps(value, sort_keys=True):
                return False
        elif current != value:
            return False
    return True


def validate_restore_journal(session, events):
    """Reject a stale or divergent checkpoint before publication can write."""
    incoming = {event["event_id"]: event_values(event) for event in events}
    for existing in session.query(SystemMemoryEventModel).yield_per(256):
        values = incoming.get(existing.event_id)
        if values is None:
            raise StateRestoreError(
                "The restore snapshot omits committed Journal events from the target database. "
                "Use a current snapshot or restore an independent checkpoint database."
            )
        if not event_matches(existing, values):
            raise StateRestoreError(
                "The restore snapshot changes immutable Journal event "
                f"{existing.event_id!r} in the target database."
            )
