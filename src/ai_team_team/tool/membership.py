"""AgentTeam membership administration and voting tools."""

from typing import Any, Dict, Optional

from ..core.exceptions import ToolArgumentError, ToolBusinessError, ToolPermissionError
from .context import _resolve_actual_agent, _resolve_actual_team
from .contract import Tool
from .models import MembershipProposalArguments


def build_membership_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str:
        """Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if team_id not in att_manager.teams:
            raise ToolBusinessError(f"Team {team_id!r} was not found.")
            
        child = att_manager.teams[team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            raise ToolPermissionError(
                f"AgentTeam {actual_team.team_id!r} is not the parent of child {team_id!r}."
            )
            
        from ..core import Agent
        client = None
        if model_name and model_name != "default":
            if model_name in att_manager.llm_clients:
                client = att_manager.llm_clients[model_name]
            elif model_name in att_manager.model_configs and att_manager.generator_handler:
                from ..core import HandlerClientAdapter
                client = HandlerClientAdapter(model_name, att_manager.generator_handler)
                client._supports_native = (
                    att_manager.model_configs.get(model_name, {}).get(
                        "supports_native_tool_calling"
                    )
                    is True
                )
            else:
                available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                raise ToolArgumentError(
                    f"Model {model_name!r} is not registered. Available models: {available}."
                )
        else:
            from ..core import ManagerDefaultClientAdapter
            client = ManagerDefaultClientAdapter(att_manager)
            
        async with child.state_lock:
            new_agent = Agent(
                name=att_manager.unique_agent_name(
                    f"Dynamic_{role_name}", child
                ),
                role=role_name,
                llm_client=client,
                role_description=role_description,
                system_instructions=system_instructions
            )
            if any(member.name == new_agent.name for member in child.members):
                raise ToolBusinessError(f"Member {new_agent.name!r} already exists.")
            child.members.append(new_agent)
            att_manager.register_agent(new_agent, auto_save=False)
        att_manager._auto_save(
            agents={new_agent.agent_id},
            teams={child.team_id},
            libraries={new_agent.private_doc_library_id},
        )
        return f"Successfully added new member '{new_agent.name}' (Role: {role_name}) to team '{team_id}'."

    async def remove_team_member(team_id: str, agent_name: str) -> str:
        """Administratively removes a member from a child team. Arguments: team_id (str), agent_name (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if team_id not in att_manager.teams:
            raise ToolBusinessError(f"Team {team_id!r} was not found.")
            
        child = att_manager.teams[team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            raise ToolPermissionError(
                f"AgentTeam {actual_team.team_id!r} is not the parent of child {team_id!r}."
            )
            
        async with child.state_lock:
            min_size = att_manager.config.min_subagent_team_size
            if len(child.members) <= min_size:
                raise ToolBusinessError(
                    f"AgentTeam {team_id!r} must maintain at least {min_size} members."
                )

            target_agent = None
            for m in child.members:
                if m.name == agent_name:
                    target_agent = m
                    break
            if not target_agent:
                raise ToolBusinessError(
                    f"Member {agent_name!r} was not found in AgentTeam {team_id!r}."
                )

            child.members.remove(target_agent)
        att_manager._auto_save(teams={child.team_id})
        return f"Successfully removed member '{agent_name}' from team '{team_id}'."

    async def initiate_membership_vote(
        action: str,
        target: str,
        rationale: str,
        initiator_type: str = "individual",
        proposed_details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Initiates a democratic vote to add or remove a team member. Arguments: action (str - 'add' or 'remove'), target (str - role name for 'add', agent name for 'remove'), rationale (str), initiator_type (str - 'individual' or 'AT'), proposed_details (dict - containing 'model', 'role_description', 'system_instructions' if action is 'add')"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            raise ToolPermissionError("Membership voting is disabled.")
            
        if action == "add" and proposed_details:
            model_name = proposed_details.get("model")
            if model_name and model_name != "default":
                if model_name not in att_manager.llm_clients and model_name not in att_manager.model_configs:
                    available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                    raise ToolArgumentError(
                        f"Model {model_name!r} is not registered. Available models: {available}."
                    )

        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        if action not in {"add", "remove"}:
            raise ToolArgumentError("action must be 'add' or 'remove'.")
        if initiator_type not in {"individual", "AT"}:
            raise ToolArgumentError("initiator_type must be 'individual' or 'AT'.")
        if initiator_type == "individual":
            if actual_agent is None or actual_agent not in actual_team.members:
                raise ToolPermissionError(
                    "Only an active AgentTeam member can initiate an individual proposal."
                )

        import uuid
        vp_id = f"VP-{uuid.uuid4().hex[:6]}"
        initiator_name = (
            actual_agent.name if initiator_type == "individual" else "AT"
        )
        
        proposal = {
            "proposal_id": vp_id,
            "action": action,
            "target": target,
            "initiator_type": initiator_type,
            "initiator_name": initiator_name,
            "initiator_agent_id": (
                actual_agent.agent_id
                if initiator_type == "individual"
                else None
            ),
            "rationale": rationale,
            "proposed_details": proposed_details or {},
            "votes": {},
            "status": "active"
        }
        
        if initiator_type == "individual":
            proposal["votes"][actual_agent.agent_id] = {
                "vote": "Agree",
                "public": True,
                "rationale": "Initiated proposal.",
            }
            
        async with actual_team.state_lock:
            actual_team.proposals[vp_id] = proposal
        att_manager._auto_save(proposals={actual_team.team_id})
        return f"Vote proposal '{vp_id}' successfully initiated. Other members must vote using 'cast_vote'."

    async def cast_vote(proposal_id: str, vote: str, public: bool = True, rationale: str = "") -> str:
        """Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            raise ToolPermissionError("Membership voting is disabled.")
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        if actual_agent is None or actual_agent not in actual_team.members:
            raise ToolPermissionError("Only an active team member can vote.")
        caller_agent_name = actual_agent.name
        caller_agent_id = actual_agent.agent_id
        new_agent = None
        membership_changed = False

        async with actual_team.state_lock:
            if proposal_id not in actual_team.proposals:
                raise ToolBusinessError(f"Proposal {proposal_id!r} was not found.")
                
            prop = actual_team.proposals[proposal_id]
            if prop.get("status") != "active":
                raise ToolBusinessError(
                    f"Proposal {proposal_id!r} is already closed with status {prop.get('status')!r}."
                )
                
            if vote not in {"Agree", "Disagree", "Abstain"}:
                raise ToolArgumentError(
                    "vote must be 'Agree', 'Disagree', or 'Abstain'."
                )
            if caller_agent_id in prop["votes"]:
                raise ToolBusinessError(
                    f"Member {caller_agent_name!r} has already voted."
                )

            prop["votes"][caller_agent_id] = {
                "vote": vote,
                "public": bool(public),
                "rationale": rationale,
            }

            total_members = len(actual_team.members)
            if len(prop["votes"]) < total_members:
                result = f"Successfully cast vote on proposal '{proposal_id}'."
            else:
                agree_count = sum(
                    1
                    for ballot in prop["votes"].values()
                    if ballot["vote"] == "Agree"
                )
                ratio = agree_count / total_members
                if ratio < (2 / 3):
                    prop["status"] = "rejected"
                    result = (
                        f"Proposal '{proposal_id}' rejected "
                        f"({agree_count}/{total_members} Agree, threshold is 2/3)."
                    )
                else:
                    prop["status"] = "approved"
                    details = prop.setdefault("proposed_details", {})
                    if getattr(actual_team, "is_running", False):
                        details["executed"] = False
                        if prop["action"] == "remove" and len(
                            actual_team.members
                        ) <= att_manager.config.min_subagent_team_size:
                            prop["status"] = "rejected"
                            result = (
                                f"Proposal '{proposal_id}' failed execution. "
                                "Removing the member would violate minimum "
                                "team size constraints."
                            )
                        else:
                            result = (
                                f"Proposal '{proposal_id}' approved "
                                f"({agree_count}/{total_members} Agree). "
                                "Membership execution is deferred to the end "
                                "of the current round."
                            )
                    elif details.get("executed", False):
                        result = f"Proposal '{proposal_id}' was already executed."
                    elif prop["action"] == "add":
                        details["executed"] = True
                        role_name = prop["target"]
                        model_name = details.get("model")
                        role_desc = details.get("role_description", "")
                        sys_inst = details.get("system_instructions", "")
                        if model_name and model_name != "default":
                            if model_name in att_manager.llm_clients:
                                client = att_manager.llm_clients[model_name]
                            elif (
                                model_name in att_manager.model_configs
                                and att_manager.generator_handler
                            ):
                                from ..core import HandlerClientAdapter

                                client = HandlerClientAdapter(
                                    model_name, att_manager.generator_handler
                                )
                                client._supports_native = (
                                    att_manager.model_configs.get(
                                        model_name, {}
                                    ).get("supports_native_tool_calling")
                                    is True
                                )
                            else:
                                prop["status"] = "rejected"
                                result = (
                                    f"Proposal '{proposal_id}' failed execution because model {model_name!r} is not registered."
                                )
                                client = None
                        else:
                            from ..core import ManagerDefaultClientAdapter

                            client = ManagerDefaultClientAdapter(att_manager)
                        if client is not None:
                            from ..core import Agent

                            new_agent = Agent(
                                name=att_manager.unique_agent_name(
                                    f"Dynamic_{role_name}", actual_team
                                ),
                                role=role_name,
                                llm_client=client,
                                role_description=role_desc,
                                system_instructions=sys_inst,
                            )
                            if any(
                                member.name == new_agent.name
                                for member in actual_team.members
                            ):
                                prop["status"] = "rejected"
                                result = (
                                    f"Proposal '{proposal_id}' failed execution because member {new_agent.name!r} already exists."
                                )
                                new_agent = None
                            else:
                                actual_team.members.append(new_agent)
                                att_manager.register_agent(
                                    new_agent, auto_save=False
                                )
                                membership_changed = True
                                result = (
                                    f"Proposal '{proposal_id}' approved "
                                    f"({agree_count}/{total_members} Agree). "
                                    f"Added new member '{new_agent.name}' to the team!"
                                )
                    else:
                        details["executed"] = True
                        min_size = att_manager.config.min_subagent_team_size
                        target_agent = next(
                            (
                                member
                                for member in actual_team.members
                                if member.name == prop["target"]
                            ),
                            None,
                        )
                        if len(actual_team.members) <= min_size:
                            prop["status"] = "rejected"
                            result = (
                                f"Proposal '{proposal_id}' failed execution. "
                                "Removing the member would violate minimum "
                                "team size constraints."
                            )
                        elif target_agent is None:
                            prop["status"] = "rejected"
                            result = (
                                f"Proposal '{proposal_id}' failed execution. "
                                f"Member '{prop['target']}' not found."
                            )
                        else:
                            actual_team.members.remove(target_agent)
                            membership_changed = True
                            result = (
                                f"Proposal '{proposal_id}' approved "
                                f"({agree_count}/{total_members} Agree). "
                                f"Removed member '{target_agent.name}' from the team!"
                            )

        changed_agents = {new_agent.agent_id} if new_agent is not None else set()
        att_manager._auto_save(
            agents=changed_agents,
            teams=(
                {actual_team.team_id}
                if membership_changed
                else set()
            ),
            proposals={actual_team.team_id},
            libraries=(
                {new_agent.private_doc_library_id}
                if new_agent is not None
                else set()
            ),
        )
        return result

    async def retract_membership_vote(proposal_id: str) -> str:
        """Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            raise ToolPermissionError("Membership voting is disabled.")
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        if actual_agent is None or actual_agent not in actual_team.members:
            raise ToolPermissionError(
                "Only an active AgentTeam member can retract a proposal."
            )
        caller_agent_name = actual_agent.name
        caller_agent_id = actual_agent.agent_id
            
        async with actual_team.state_lock:
            if proposal_id not in actual_team.proposals:
                raise ToolBusinessError(f"Proposal {proposal_id!r} was not found.")
                
            prop = actual_team.proposals[proposal_id]
            if prop.get("status") != "active":
                raise ToolBusinessError(f"Proposal {proposal_id!r} is already closed.")
                
            initiator_name = prop.get("initiator_name")
            if (
                prop.get("initiator_type") == "individual"
                and prop.get("initiator_agent_id") != caller_agent_id
            ):
                raise ToolPermissionError(
                    f"Only the initiator {initiator_name!r} can retract this proposal."
                )
                
            prop["status"] = "retracted"
        att_manager._auto_save(proposals={actual_team.team_id})
        return f"Successfully retracted proposal '{proposal_id}'."

    tools = {
        "add_team_member": Tool(
            "add_team_member",
            "Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)",
            add_team_member,
        ),
        "remove_team_member": Tool(
            "remove_team_member",
            "Administratively removes a member from a child team. Arguments: team_id (str), agent_name (str)",
            remove_team_member,
        ),
        "initiate_membership_vote": Tool(
            "initiate_membership_vote",
            "Initiates a democratic vote to add or remove a team member.",
            initiate_membership_vote,
            schema=MembershipProposalArguments,
            prompt_schema_mode="full",
            examples=[
                {
                    "action": "add",
                    "target": "Security Reviewer",
                    "rationale": "The team needs an independent security review.",
                    "proposed_details": {
                        "model": "default",
                        "role_description": "Review security boundaries.",
                    },
                }
            ],
        ),
        "cast_vote": Tool(
            "cast_vote",
            "Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)",
            cast_vote,
        ),
        "retract_membership_vote": Tool(
            "retract_membership_vote",
            "Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)",
            retract_membership_vote,
        ),
    }
    return tools

