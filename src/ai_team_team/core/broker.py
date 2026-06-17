import logging
from typing import Tuple, Any
from .team import AgentTeam

class NegotiationBroker:
    """Coordinates sibling and cross-lineage communication permissions."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager
        self.logger = logging.getLogger("NegotiationBroker")
        self.peer_talk_agreements = set() # Set of Tuple[str, str] (sender_id, recipient_id)

    async def negotiate_communication(self, sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        if sender_parent and recipient_parent and sender_parent.team_id == recipient_parent.team_id:
            parent = sender_parent
            allow = parent.communication_rules.get("allow_sibling_talk", False)
            self.logger.info(f"Sibling negotiation between {sender.team_id} and {recipient.team_id}: Parent {parent.team_id} decision={allow}")
            return allow

        # Check for negotiated cross-lineage peer agreement
        pair = (sender.team_id, recipient.team_id)
        if pair in self.peer_talk_agreements:
            return True

        self.logger.warning(f"Communication denied between {sender.team_id} and {recipient.team_id}. No active agreement exists.")
        return False

    async def establish_peer_agreement(self, sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        if not sender_parent or not recipient_parent:
            self.logger.warning(f"Lineage incomplete. Cannot establish peer agreement between {sender.team_id} and {recipient.team_id}.")
            return False

        self.logger.info(f"Cross-lineage peer talk negotiation requested between {sender.team_id} and {recipient.team_id}.")
        success = await self._run_parent_negotiation_loop(sender_parent, recipient_parent, mode)
        if success:
            self.peer_talk_agreements.add((sender.team_id, recipient.team_id))
            self.manager._auto_save()
            return True
        return False

    async def _run_parent_negotiation_loop(self, p1: AgentTeam, p2: AgentTeam, mode: str) -> bool:
        self.logger.info(f"Parents {p1.team_id} and {p2.team_id} are negotiating communication channel (mode: {mode})...")
        if mode in {"proxied", "indirect", "rule_gated"}:
            self.logger.info("Negotiation loop succeeded: communication contract established.")
            return True
        self.logger.warning(f"Negotiation loop rejected: mode '{mode}' is unsupported or unsafe.")
        return False
