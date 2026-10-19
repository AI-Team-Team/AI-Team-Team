"""Owner-authorized chat values, independent of personal model memory and file ACLs."""

import hashlib
import json
from typing import Literal

from pydantic import Field

from .activity.contracts.base import ContractRecord, Identifier
from .activity.contracts.api import ChatMessageSummary
from ai_team_team.gated_reader import FileReadResult


def _command_digest(command, arguments):
    """Bind an owner-scoped receipt to its exact, canonical command input."""
    wire = json.dumps([command, arguments], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(wire.encode()).hexdigest()


class ChatOperationResult(ContractRecord):
    status: Literal["EDITED", "WITHDRAWN", "MARK_MESSAGE_READ", "MARK_MESSAGE_UNREAD", "DELETE_MESSAGE",
                    "RESTORE_MESSAGE", "PREFERENCES_UPDATED", "ALREADY_FRIENDS", "PENDING", "STALE_REQUEST",
                    "ALREADY_RESOLVED", "ACCEPTED", "REJECTED", "IGNORED", "CANCELLED", "BLOCKED",
                    "UNBLOCKED", "REMOVED", "REFUSAL_LIFTED", "UNCHANGED"]
    message_id: str | None = None
    request_id: str | None = None
    relationship_id: str | None = None
    version: int | None = Field(default=None, gt=0)
    generation: int | None = Field(default=None, gt=0)
    durability: Literal["durable", "volatile"]
    state_version: int = Field(gt=0)


class ChatReadResult(FileReadResult):
    message_id: Identifier
    version: int = Field(gt=0)
    withdrawn: bool
    frozen: bool
    reply_message_id: str | None = None


class ChatRelationship(ContractRecord):
    relationship_id: str
    other_agent_id: str
    generation: int = Field(gt=0)
    friendship: bool
    blocked_by_self: bool
    blocked_by_other: bool
    refusal_by_self: bool
    refusal_by_other: bool
    remaining_messages: int = Field(ge=0, le=3)


class FriendshipRequestView(ContractRecord):
    request_id: str
    relationship_id: str
    sender_agent_id: str
    recipient_agent_id: str
    generation: int = Field(gt=0)
    status: Literal["pending", "accepted", "rejected", "ignored", "cancelled", "stale"]
    created_at: float
    responded_at: float | None


class ChatReminderSummary(ChatMessageSummary):
    notification_id: Identifier


class ChatReminderPage(ContractRecord):
    items: tuple[ChatReminderSummary, ...]
    total_count: int = Field(ge=0)
    next_cursor: str | None = None
