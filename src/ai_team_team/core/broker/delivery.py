"""Durable AT-addressed delivery with personal reference notifications."""

import time

from ..communication import CommunicationOperationResult, PeerMessage


class BrokerDeliveryMixin:
    async def send_peer_message(self, sender, recipient, initiated_by_agent_id, content, *, invocation_id=None):
        manager = self.manager
        async with self._transaction_lock, manager._topology.transition_lock, manager._activity.lock:
            self._validate_endpoints_and_actor(sender, recipient, initiated_by_agent_id)
            if type(content) is not str or not content:
                raise ValueError("Peer message content must be nonempty text.")
            if sender is recipient:
                return CommunicationOperationResult(status="NO_AGREEMENT", reason="Peer endpoints must differ.")
            if invocation_id is not None:
                prior = next((item for item in self.peer_messages.values() if item.invocation_id == invocation_id), None)
                if prior is not None:
                    if (prior.sender_team_id, prior.recipient_team_id, prior.initiated_by_agent_id, prior.content) != (
                            sender.team_id, recipient.team_id, initiated_by_agent_id, content):
                        raise ValueError("The invocation is already bound to another peer delivery.")
                    return CommunicationOperationResult(status="DELIVERED", reason="This delivery already committed.",
                        message_id=prior.message_id, agreement_id=prior.agreement_id, team_id=recipient.team_id)
            agreement = None
            if manager.config.communication.policy != "permissive" and not (sender.is_independent and recipient.is_independent):
                agreement = self.active_agreement(sender.team_id, recipient.team_id)
                if agreement is None:
                    return CommunicationOperationResult(status="NO_AGREEMENT",
                        reason="Call request_peer_communication() before sending on this route.", team_id=recipient.team_id)
            message = PeerMessage(sender_team_id=sender.team_id, recipient_team_id=recipient.team_id,
                initiated_by_agent_id=initiated_by_agent_id, agreement_id=agreement.agreement_id if agreement else None,
                content=content, invocation_id=invocation_id)
            operation_id = f"PEER-{message.message_id}"
            staged_mails, notices = [], ()
            with self.stage() as candidate:
                self.peer_messages[message.message_id] = message
                dirty = manager._new_dirty_state()
                dirty["peer_messages"].add(message.message_id)
                dirty["inboxes"].add(recipient.team_id)
                try:
                    for member in recipient.members:
                        mail_id = f"PEER-{message.message_id}-{member.agent_id}"
                        manager._inbox.notify(member.agent_id, "peer_message_arrived",
                            {"message_id": message.message_id, "sender_team_id": sender.team_id,
                             "recipient_team_id": recipient.team_id,
                             "instruction": "Use read_peer_message within the receiving AgentTeam scope to read this AT-addressed message."},
                            message_id=mail_id, staged=True)
                        staged_mails.append((member, mail_id))
                        dirty["agent_inboxes"].add(member.agent_id)
                    records, notices = manager._activity.mail_records(dirty["agent_inboxes"])
                    await manager._records.commit(records, dirty=dirty, broker_state=candidate, operation_id=operation_id,
                        notifications=notices, team_inboxes={
                            recipient.team_id: (*recipient.message_inbox, message.to_inbox_message())})
                finally:
                    if operation_id not in manager._records.receipts:
                        for member, mail_id in staged_mails:
                            with member.inbox_lock:
                                member.agent_inbox[:] = [mail for mail in member.agent_inbox if mail["message_id"] != mail_id]
                    manager._inbox.finish_staged(mail_id for _member, mail_id in staged_mails)
                    for notice_id in notices:
                        if ("agent_notifications", (notice_id,)) in manager._records.index:
                            manager._activity.schedule_notice(notice_id)
            manager._emit_callback("on_system_event", "peer_message_delivered",
                {"message_id": message.message_id, "sender_team_id": sender.team_id,
                 "recipient_team_id": recipient.team_id, "agreement_id": message.agreement_id})
            return CommunicationOperationResult(status="DELIVERED", reason="The addressed message and references committed.",
                message_id=message.message_id, agreement_id=message.agreement_id, team_id=recipient.team_id)

    async def revoke_agreement(self, agreement_id, actor_team_id, reason):
        manager = self.manager
        async with self._transaction_lock, manager._topology.transition_lock, manager._activity.lock:
            prior = self.agreements.get(agreement_id)
            if prior is None or actor_team_id not in {prior.source_team_id, prior.target_team_id}:
                return CommunicationOperationResult(status="FORBIDDEN", reason="Only a channel endpoint may revoke.")
            actor, scope = manager._active_tool_agent.get(), manager._active_team.get()
            if actor is not None and (scope is None or scope.team_id != actor_team_id or actor not in scope.members
                    or actor.lifecycle_state != "active"):
                raise PermissionError("Revocation requires current endpoint membership.")
            if not prior.active:
                return CommunicationOperationResult(status="ALREADY_REVOKED", reason="The channel is already inactive.",
                    agreement_id=agreement_id)
            with self.stage() as candidate:
                agreement = prior.model_copy(deep=True)
                agreement.active, agreement.revoked_at = False, time.time()
                agreement.revoked_by_team_id, agreement.revoke_reason = actor_team_id, reason
                self.agreements[agreement_id] = agreement
                dirty = manager._new_dirty_state()
                dirty["communication_agreements"].add(agreement_id)
                await manager._records.commit((), dirty=dirty, broker_state=candidate)
            manager._emit_callback("on_system_event", "communication_agreement_revoked",
                {"agreement_id": agreement_id, "revoked_by_team_id": actor_team_id})
            return CommunicationOperationResult(status="REVOKED", reason="The channel was revoked.", agreement_id=agreement_id)
