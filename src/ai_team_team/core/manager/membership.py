"""Deferred AgentTeam membership mutation workflow."""

from typing import TYPE_CHECKING

from ..adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ..agent import Agent
from ..team import AgentTeam

if TYPE_CHECKING:
    from .facade import ATTManager


class MembershipService:
    """Owns once-only application of approved membership proposals."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    async def _apply_deferred_membership_changes(self, team: AgentTeam) -> None:
        """Applies each approved membership proposal at most once."""
        manager = self.manager
        changed_agents: set[str] = set()
        changed = False
        membership_changed = False
        async with manager._messaging.membership_transaction(team) as change:
            for proposal in change.proposals.values():
                details = proposal.setdefault("proposed_details", {})
                if proposal.get("status") != "approved" or details.get("executed") is True:
                    continue

                details["executed"] = True
                changed = True
                action = proposal.get("action")
                target = proposal.get("target")
                if action == "add":
                    model_name = details.get("model")
                    if model_name and model_name != "default":
                        if model_name in manager.llm_clients:
                            client = manager.llm_clients[model_name]
                        elif model_name in manager.model_configs and manager.generator_handler:
                            client = HandlerClientAdapter(model_name, manager.generator_handler)
                            client._supports_native = (
                                manager.model_configs.get(model_name, {}).get(
                                    "supports_native_tool_calling"
                                )
                                is True
                            )
                        else:
                            proposal["status"] = "rejected"
                            manager.logger.warning(
                                "Deferred membership add rejected: model %r is unavailable.",
                                model_name,
                            )
                            continue
                    else:
                        client = ManagerDefaultClientAdapter(manager)

                    new_agent = Agent(
                        name=manager.unique_agent_name(f"Dynamic_{target}", team),
                        role=target,
                        llm_client=client,
                        role_description=details.get("role_description", ""),
                        system_instructions=details.get("system_instructions", ""),
                    )
                    if any(member.name == new_agent.name for member in change.members):
                        proposal["status"] = "rejected"
                        continue
                    change.register_agent(new_agent)
                    change.members.append(new_agent)
                    changed_agents.add(new_agent.agent_id)
                    membership_changed = True
                    manager.logger.info(
                        "Deferred execution added member %s to team %s.",
                        new_agent.name,
                        team.team_id,
                    )
                elif action == "remove":
                    if len(change.members) <= manager.config.min_subagent_team_size:
                        proposal["status"] = "rejected"
                        continue
                    target_agent = next(
                        (member for member in change.members if member.name == target),
                        None,
                    )
                    if target_agent is None:
                        proposal["status"] = "rejected"
                        continue
                    change.members.remove(target_agent)
                    membership_changed = True
                    manager.logger.info(
                        "Deferred execution removed member %s from team %s.",
                        target,
                        team.team_id,
                    )
                else:
                    proposal["status"] = "rejected"
