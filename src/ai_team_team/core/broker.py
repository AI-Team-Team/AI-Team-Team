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
        policy_name = getattr(self.manager.config, "communication_policy", "permissive")
        if policy_name == "permissive":
            return True

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

    async def establish_peer_agreement(self, sender: AgentTeam, recipient: AgentTeam, rationale: str, mode: str = None) -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        self.logger.info(f"Cross-lineage peer talk negotiation requested between {sender.team_id} and {recipient.team_id}.")
        from .policies import resolve_communication_policy
        policy_name = getattr(self.manager.config, "communication_policy", "permissive")
        if mode is not None:
            policy_name = mode
            
        policy = resolve_communication_policy(policy_name)
        success = await policy.authorize_peer_talk(sender, recipient, self.manager, rationale)
        if success:
            self.peer_talk_agreements.add((sender.team_id, recipient.team_id))
            self.peer_talk_agreements.add((recipient.team_id, sender.team_id))
            self.manager._auto_save()
            return True
        return False
