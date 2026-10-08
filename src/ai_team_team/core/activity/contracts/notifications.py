"""Delivery, model presentation, read receipts, and decisions stay separate."""

from typing import Literal

from .base import ContractRecord, Identifier, PositiveInteger


class NotificationSource(ContractRecord):
    kind: Literal["team_message", "direct_message", "personal_mail", "execution", "system_event"]
    source_id: Identifier


class NotificationReference(ContractRecord):
    notification_id: Identifier
    recipient_agent_id: Identifier
    source: NotificationSource
    classification: Literal["ordinary", "membership", "permission", "health", "recovery"]
    arrival_generation: PositiveInteger
    deduplication_key: Identifier


class PresentationClaim(ContractRecord):
    """Uncertain perception never becomes a domain read receipt or a ballot."""

    notification_id: Identifier
    frame_id: Identifier
    model_request_id: Identifier
    state: Literal["reserved", "dispatched", "presented", "uncertain"]


class SourceDeliveryReceipt(ContractRecord):
    status: Literal["DELIVERED"] = "DELIVERED"
    message_id: Identifier
    notification_ids: tuple[Identifier, ...]
    durability: Literal["durable", "volatile"]
    state_version: PositiveInteger
