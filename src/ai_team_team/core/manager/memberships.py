"""Once-only membership effects inside the existing relationship transaction."""

from ..adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ..agent import Agent


class MembershipService:
    def __init__(self, manager):
        self.manager = manager

    def execute_approved(self, change, team, proposal):
        """Stage effects now; no discussion boundary or person's owned-field edit."""
        if proposal.get("status") != "approved":
            raise ValueError("Only an approved proposal can publish membership effects.")
        details = proposal.setdefault("proposed_details", {})
        if details.get("executed") is True:
            return "The approved proposal was already executed."
        details["executed"] = True
        action, target = proposal["action"], proposal["target"]
        if action == "add":
            alias = details.get("model") or "default"
            if alias == "default":
                client = ManagerDefaultClientAdapter(self.manager)
            elif alias in self.manager.llm_clients:
                client = self.manager.llm_clients[alias]
            elif alias in self.manager.model_configs and self.manager.generator_handler:
                client = HandlerClientAdapter(alias, self.manager.generator_handler)
                client._supports_native = self.manager.model_configs[alias].get("supports_native_tool_calling") is True
            else:
                proposal["status"] = "rejected"
                return "The proposed model alias is not available."
            person = Agent(self.manager.unique_agent_name(f"Dynamic_{target}", team), target, client,
                role_description=details.get("role_description", ""),
                system_instructions=details.get("system_instructions", ""))
            change.register_agent(person)
            change.members.append(person)
            return f"Added new member '{person.name}' to the team."
        if action != "remove":
            proposal["status"] = "rejected"
            return "Unknown membership action."
        person = next((member for member in change.members if member.name == target), None)
        if person is None or len(change.members) <= self.manager.config.min_subagent_team_size:
            proposal["status"] = "rejected"
            return "The member is unavailable or removal would violate minimum team size."
        change.members.remove(person)
        return f"Removed member '{person.name}' from the team."

    async def apply_approved_proposals(self, team):
        """Host recovery adapter for explicitly stored, unexecuted approved effects."""
        if self.manager._active_tool_agent.get() is not None:
            raise PermissionError("Tools apply their own ballot effects in the same transaction.")
        async with self.manager._messaging.membership_transaction(team) as change:
            for proposal in change.proposals.values():
                if proposal.get("status") == "approved" and not proposal.get("proposed_details", {}).get("executed"):
                    self.execute_approved(change, team, proposal)
