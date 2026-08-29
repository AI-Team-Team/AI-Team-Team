"""Durable peer-message delivery and agreement revocation."""

from __future__ import annotations

import time
from typing import Optional

from ..communication import (
    CommunicationAgreement,
    CommunicationOperationResult,
    PeerMessage,
)
from ..team import AgentTeam


class BrokerDeliveryMixin:
    async def send_peer_message(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        content: str,
        *,
        invocation_id: Optional[str] = None,
    ) -> CommunicationOperationResult:
        async with self._transaction_lock:
            return await self._send_peer_message_transaction(
                sender,
                recipient,
                initiated_by_agent_id,
                content,
                invocation_id=invocation_id,
            )

    async def _send_peer_message_transaction(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        content: str,
        *,
        invocation_id: Optional[str] = None,
    ) -> CommunicationOperationResult:
        self._validate_endpoints_and_actor(
            sender, recipient, initiated_by_agent_id
        )
        if sender is recipient:
            return CommunicationOperationResult(
                status="NO_AGREEMENT",
                reason="Peer communication requires a different AgentTeam.",
                team_id=recipient.team_id,
            )
        policy = self.manager.config.communication
        async with self._locked_state():
            agreement = None
            if policy.policy != "permissive":
                agreement = self.active_agreement(
                    sender.team_id, recipient.team_id
                )
                if agreement is None:
                    return CommunicationOperationResult(
                        status="NO_AGREEMENT",
                        reason=(
                            "No active communication channel permits this "
                            "route. Call request_peer_communication() first."
                        ),
                        team_id=recipient.team_id,
                    )
            if invocation_id:
                existing = next(
                    (
                        message
                        for message in self.peer_messages.values()
                        if message.invocation_id == invocation_id
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        existing.sender_team_id != sender.team_id
                        or existing.recipient_team_id != recipient.team_id
                        or existing.initiated_by_agent_id
                        != initiated_by_agent_id
                        or existing.content != content
                    ):
                        raise ValueError(
                            "The tool invocation ID is already bound to a "
                            "different peer message."
                        )
                    return CommunicationOperationResult(
                        status="DELIVERED",
                        reason="The peer message was already delivered.",
                        message_id=existing.message_id,
                        agreement_id=existing.agreement_id,
                        team_id=existing.recipient_team_id,
                    )
            peer_message = PeerMessage(
                sender_team_id=sender.team_id,
                recipient_team_id=recipient.team_id,
                initiated_by_agent_id=initiated_by_agent_id,
                agreement_id=(agreement.agreement_id if agreement else None),
                content=content,
                invocation_id=invocation_id,
            )
            self.peer_messages[peer_message.message_id] = peer_message
            with recipient.inbox_lock:
                recipient.message_inbox.append(
                    peer_message.to_inbox_message()
                )

        dirty = self.manager._new_dirty_state()
        dirty["peer_messages"].add(peer_message.message_id)
        dirty["inboxes"].add(recipient.team_id)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                self.peer_messages.pop(peer_message.message_id, None)
                with recipient.inbox_lock:
                    recipient.message_inbox = [
                        item
                        for item in recipient.message_inbox
                        if item.get("message_id") != peer_message.message_id
                    ]
            raise
        self.manager._emit_callback(
            "on_system_event",
            "peer_message_delivered",
            {
                "message_id": peer_message.message_id,
                "sender_team_id": sender.team_id,
                "recipient_team_id": recipient.team_id,
                "agreement_id": peer_message.agreement_id,
            },
        )
        return CommunicationOperationResult(
            status="DELIVERED",
            reason="The peer message was durably delivered.",
            message_id=peer_message.message_id,
            agreement_id=peer_message.agreement_id,
            team_id=recipient.team_id,
        )

    async def revoke_agreement(
        self, agreement_id: str, actor_team_id: str, reason: str
    ) -> CommunicationOperationResult:
        async with self._transaction_lock:
            return await self._revoke_agreement_transaction(
                agreement_id, actor_team_id, reason
            )

    async def _revoke_agreement_transaction(
        self, agreement_id: str, actor_team_id: str, reason: str
    ) -> CommunicationOperationResult:
        async with self._locked_state():
            agreement = self.agreements.get(agreement_id)
            if agreement is None:
                return CommunicationOperationResult(
                    status="FORBIDDEN", reason="Unknown communication agreement."
                )
            if actor_team_id not in {
                agreement.source_team_id,
                agreement.target_team_id,
            }:
                return CommunicationOperationResult(
                    status="FORBIDDEN",
                    reason="Only an endpoint AgentTeam may revoke this agreement.",
                    agreement_id=agreement_id,
                )
            if not agreement.active:
                return CommunicationOperationResult(
                    status="ALREADY_REVOKED",
                    reason="The agreement is already inactive.",
                    agreement_id=agreement_id,
                )
            agreement_before = agreement.model_copy(deep=True)
            agreement.active = False
            agreement.revoked_at = time.time()
            agreement.revoked_by_team_id = actor_team_id
            agreement.revoke_reason = reason

        dirty = self.manager._new_dirty_state()
        dirty["communication_agreements"].add(agreement_id)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                self.agreements[agreement_id] = agreement_before
            raise
        self.manager._emit_callback(
            "on_system_event",
            "communication_agreement_revoked",
            {
                "agreement_id": agreement_id,
                "revoked_by_team_id": actor_team_id,
            },
        )
        return CommunicationOperationResult(
            status="REVOKED",
            reason="The communication agreement was revoked.",
            agreement_id=agreement_id,
        )

