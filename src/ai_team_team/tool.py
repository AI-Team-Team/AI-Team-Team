import logging
from typing import Dict, Any, Optional, Callable, List, Tuple

logger = logging.getLogger("ATT.Tools")

class Tool:
    """Encapsulates an AI tool with name, description, and execution logic."""
    def __init__(self, name: str, description: str, func: Callable[..., Any]):
        self.name = name
        self.description = description
        self.func = func

    def __call__(self, *args, **kwargs) -> str:
        try:
            res = self.func(*args, **kwargs)
            return str(res)
        except Exception as e:
            from .core import ATTException
            if isinstance(e, ATTException):
                raise e
            logger.error(f"Error executing tool '{self.name}': {e}")
            return f"Error executing tool '{self.name}': {e}"

def get_default_tools(context: Dict[str, Any], caller_node: Any) -> Dict[str, Tool]:
    """
    Centralized factory that registers and returns the default set of generic autonomy tools.
    
    Context dictionary requires:
      - 'att_manager': ATTManager (for dynamic spawning and escalations)
    """
    att_manager = context.get("att_manager")

    def dispatch_subagent(
        task: str,
        team_purpose: str,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        system_instructions: str = "",
        allow_sibling_talk: bool = False,
        sibling_talk_rules: str = ""
    ) -> str:
        """Spawns a recursive child AT under the ATT tree. Each AT (AI-Team) must have at least 3 Agents. Arguments: task (str), team_purpose (str), member_configs (dict), system_instructions (str), allow_sibling_talk (bool), sibling_talk_rules (str)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        config = att_manager.config
        if not config.enable_dynamic_delegation:
            return "Error: Dynamic Subagent Delegation is disabled in configuration."
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
        
        current_depth = actual_team.depth if actual_team else 1
        max_depth = config.max_delegation_depth
        if current_depth >= max_depth:
            return f"Error: Cannot spawn child AT. Max delegation depth ({max_depth}) reached. You must use `delegate_escalation` to ask your parent for help."

        min_size = config.min_subagent_team_size
        if member_configs:
            if not isinstance(member_configs, dict):
                return "Error: member_configs must be a dictionary mapping role names to their configs."
            member_count = len(member_configs)
            if member_count < min_size:
                return f"Error: A valid Agent Team MUST have at least {min_size} members. Please define at least {min_size} roles in member_configs to spawn this team."
        else:
            member_count = min_size

        try:
            child_team = caller_node.launch_att(
                manager=att_manager,
                member_count=member_count,
                system_instructions=system_instructions,
                team_purpose=team_purpose,
                member_configs=member_configs
            )
            
            # Setup communication rules
            child_team.communication_rules["allow_sibling_talk"] = bool(allow_sibling_talk)
            if sibling_talk_rules:
                child_team.communication_rules["rules"].append(sibling_talk_rules)

            return att_manager.execute_team_discussion(
                child_team,
                task,
                rounds=config.subagent_discussion_rounds
            )
        except Exception as e:
            return f"Dispatch Subagent Team Error: {e}"

    def delegate_escalation(objective: str, rationale: str) -> str:
        """Escalates objective upward in the ATT lineage tree. Arguments: objective (str), rationale (str)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
        
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam for the caller."

        parent = actual_team.parent_team or att_manager.find_parent_team(actual_team)
        if not parent:
            return "Error: No parent team exists to escalate to."
        
        try:
            payload = {
                "type": "escalation_spawn",
                "objective": objective,
                "rationale": rationale,
                "from": actual_team.team_id
            }
            parent.receive_message(payload)
            return f"Escalation successfully dispatched to parent team '{parent.team_id}'."
        except Exception as e:
            return f"Escalation Error: {e}"

    def set_sibling_talk(child_id: str, allow: bool = True) -> str:
        """Sets sibling talk permission for a child team. Arguments: child_id (str), allow (bool)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        if child_id not in att_manager.teams:
            return f"Error: Child team '{child_id}' is not registered."
            
        child = att_manager.teams[child_id]
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam for the caller."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{child_id}'."
            
        child.communication_rules["allow_sibling_talk"] = bool(allow)
        return f"Successfully set sibling talk for child team '{child_id}' to {allow}."

    def update_team_purpose(new_purpose: str) -> str:
        """Updates the purpose string of the caller's team. Arguments: new_purpose (str)"""
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        
        old_purpose = actual_team.team_purpose
        actual_team.team_purpose = new_purpose
        return f"Successfully updated team purpose from '{old_purpose}' to '{new_purpose}'."

    def update_team_status(purpose: str, progress: str) -> str:
        """Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)"""
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        
        actual_team.team_purpose = purpose
        actual_team.team_progress = progress
        return f"Successfully updated team purpose to '{purpose}' and progress to '{progress}'."

    def send_peer_message(team_id: str, message: str) -> str:
        """Sends a message to the inbox of a peer team using their Team ID. Arguments: team_id (str), message (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        target = att_manager.teams[team_id]
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."

        # Check sibling or peer communication permission
        allowed = att_manager.broker.negotiate_communication(actual_team, target)
        if not allowed:
            return "Error: Permission Denied. Cross-lineage channel must be negotiated via parents first."
            
        sender_id = actual_team.team_id if actual_team else "Unknown"
        target.receive_message({
            "type": "peer_message",
            "from": sender_id,
            "objective": message
        })
        return f"Message successfully delivered to team '{team_id}'."

    def negotiate_peer_talk(target_team_id: str, rationale: str) -> str:
        """Requests parents to negotiate a cross-lineage communication channel with a target team. Arguments: target_team_id (str), rationale (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if target_team_id not in att_manager.teams:
            return f"Error: Target team '{target_team_id}' not found."
            
        target = att_manager.teams[target_team_id]
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        success = att_manager.broker.establish_peer_agreement(actual_team, target)
        if success:
            return f"Success: Cross-lineage peer channel established with team '{target_team_id}'."
        else:
            return f"Negotiation Rejected: Parents could not agree on establishing communication with team '{target_team_id}'."

    def add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str:
        """Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        child = att_manager.teams[team_id]
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{team_id}'."
            
        from .core import Agent
        client = None
        if model_name in att_manager.llm_clients:
            client = att_manager.llm_clients[model_name]
        elif model_name in att_manager.model_configs and att_manager.generator_handler:
            from .core import HandlerClientAdapter
            client = HandlerClientAdapter(model_name, att_manager.generator_handler)
        else:
            from .core import ManagerCriticClientAdapter
            client = ManagerCriticClientAdapter(att_manager)
            
        new_agent = Agent(
            name=f"Dynamic_{role_name}",
            role=role_name,
            llm_client=client,
            role_description=role_description,
            system_instructions=system_instructions
        )
        child.members.append(new_agent)
        return f"Successfully added new member '{new_agent.name}' (Role: {role_name}) to team '{team_id}'."

    def remove_team_member(team_id: str, agent_name: str) -> str:
        """Administratively removes a member from a child team. Arguments: team_id (str), agent_name (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        child = att_manager.teams[team_id]
        
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{team_id}'."
            
        min_size = att_manager.config.min_subagent_team_size
        if len(child.members) <= min_size:
            return f"Error: Cannot remove member. Team '{team_id}' must maintain at least {min_size} members."
            
        target_agent = None
        for m in child.members:
            if m.name == agent_name:
                target_agent = m
                break
        if not target_agent:
            return f"Error: Member '{agent_name}' not found in team '{team_id}'."
            
        child.members.remove(target_agent)
        return f"Successfully removed member '{agent_name}' from team '{team_id}'."

    def initiate_membership_vote(
        action: str,
        target: str,
        rationale: str,
        initiator_type: str = "individual",
        proposed_details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Initiates a democratic vote to add or remove a team member. Arguments: action (str - 'add' or 'remove'), target (str - role name for 'add', agent name for 'remove'), rationale (str), initiator_type (str - 'individual' or 'AT'), proposed_details (dict - containing 'model', 'role_description', 'system_instructions' if action is 'add')"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            return "Error: Membership voting is disabled."
            
        from .core import Agent, AgentTeam
        actual_team = None
        caller_agent_name = "Unknown"
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            caller_agent_name = caller_node.name
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if action not in {"add", "remove"}:
            return "Error: Action must be 'add' or 'remove'."
            
        import uuid
        vp_id = f"VP-{uuid.uuid4().hex[:6]}"
        initiator_name = caller_agent_name if initiator_type == "individual" else "AT"
        
        proposal = {
            "proposal_id": vp_id,
            "action": action,
            "target": target,
            "initiator_type": initiator_type,
            "initiator_name": initiator_name,
            "rationale": rationale,
            "proposed_details": proposed_details or {},
            "votes": {},
            "status": "active"
        }
        
        if initiator_type == "individual" and caller_agent_name != "Unknown":
            proposal["votes"][caller_agent_name] = {"vote": "Agree", "public": True, "rationale": "Initiated proposal."}
            
        actual_team.proposals[vp_id] = proposal
        return f"Vote proposal '{vp_id}' successfully initiated. Other members must vote using 'cast_vote'."

    def cast_vote(proposal_id: str, vote: str, public: bool = True, rationale: str = "") -> str:
        """Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            return "Error: Membership voting is disabled."
            
        from .core import Agent, AgentTeam
        actual_team = None
        caller_agent_name = "Unknown"
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            caller_agent_name = caller_node.name
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if proposal_id not in actual_team.proposals:
            return f"Error: Proposal '{proposal_id}' not found."
            
        prop = actual_team.proposals[proposal_id]
        if prop.get("status") != "active":
            return f"Error: Proposal '{proposal_id}' is already closed with status '{prop.get('status')}'."
            
        if vote not in {"Agree", "Disagree", "Abstain"}:
            return "Error: Vote must be 'Agree', 'Disagree', or 'Abstain'."
            
        prop["votes"][caller_agent_name] = {
            "vote": vote,
            "public": bool(public),
            "rationale": rationale
        }
        
        total_members = len(actual_team.members)
        if len(prop["votes"]) == total_members:
            agree_count = sum(1 for v in prop["votes"].values() if v["vote"] == "Agree")
            ratio = agree_count / total_members
            
            if ratio >= (2 / 3):
                prop["status"] = "approved"
                if prop["action"] == "add":
                    role_name = prop["target"]
                    p_details = prop["proposed_details"]
                    model_name = p_details.get("model")
                    role_desc = p_details.get("role_description", "")
                    sys_inst = p_details.get("system_instructions", "")
                    
                    client = None
                    if model_name in att_manager.llm_clients:
                        client = att_manager.llm_clients[model_name]
                    elif model_name in att_manager.model_configs and att_manager.generator_handler:
                        from .core import HandlerClientAdapter
                        client = HandlerClientAdapter(model_name, att_manager.generator_handler)
                    else:
                        from .core import ManagerCriticClientAdapter
                        client = ManagerCriticClientAdapter(att_manager)
                        
                    new_agent = Agent(
                        name=f"Dynamic_{role_name}",
                        role=role_name,
                        llm_client=client,
                        role_description=role_desc,
                        system_instructions=sys_inst
                    )
                    actual_team.members.append(new_agent)
                    return f"Proposal '{proposal_id}' approved ({agree_count}/{total_members} Agree). Added new member '{new_agent.name}' to the team!"
                else:
                    agent_name = prop["target"]
                    min_size = att_manager.config.min_subagent_team_size
                    if len(actual_team.members) <= min_size:
                        prop["status"] = "rejected"
                        return f"Proposal '{proposal_id}' failed execution. Removing '{agent_name}' would violate minimum team size constraints of {min_size} members. Proposal closed as rejected."
                        
                    target_agent = None
                    for m in actual_team.members:
                        if m.name == agent_name:
                            target_agent = m
                            break
                    if not target_agent:
                        prop["status"] = "rejected"
                        return f"Proposal '{proposal_id}' failed execution. Member '{agent_name}' not found. Proposal closed as rejected."
                        
                    actual_team.members.remove(target_agent)
                    return f"Proposal '{proposal_id}' approved ({agree_count}/{total_members} Agree). Removed member '{agent_name}' from the team!"
            else:
                prop["status"] = "rejected"
                return f"Proposal '{proposal_id}' rejected ({agree_count}/{total_members} Agree, threshold is 2/3)."
                
        return f"Successfully cast vote on proposal '{proposal_id}'."

    def retract_membership_vote(proposal_id: str) -> str:
        """Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)"""
        if not att_manager or not att_manager.config.enable_membership_voting:
            return "Error: Membership voting is disabled."
            
        from .core import Agent, AgentTeam
        actual_team = None
        caller_agent_name = "Unknown"
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            caller_agent_name = caller_node.name
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if proposal_id not in actual_team.proposals:
            return f"Error: Proposal '{proposal_id}' not found."
            
        prop = actual_team.proposals[proposal_id]
        if prop.get("status") != "active":
            return f"Error: Proposal '{proposal_id}' is already closed."
            
        initiator_name = prop.get("initiator_name")
        if prop.get("initiator_type") == "individual" and initiator_name != caller_agent_name:
            return f"Error: Only the initiator '{initiator_name}' can retract this proposal."
            
        prop["status"] = "retracted"
        return f"Successfully retracted proposal '{proposal_id}'."

    def request_migration(target_parent_id: str, rationale: str) -> str:
        """Requests to migrate the caller's team to a new parent team. Arguments: target_parent_id (str), rationale (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
            
        from .core import Agent, AgentTeam
        actual_team = None
        if isinstance(caller_node, AgentTeam):
            actual_team = caller_node
        elif isinstance(caller_node, Agent):
            for team in att_manager.teams.values():
                if caller_node in team.members:
                    actual_team = team
                    break
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if target_parent_id not in att_manager.teams:
            return f"Error: Target parent team '{target_parent_id}' not found."
            
        target_parent = att_manager.teams[target_parent_id]
        if target_parent_id == actual_team.team_id:
            return "Error: Cannot migrate a team to be its own parent."
            
        def is_descendant(t, target_id):
            for child in t.child_teams:
                if child.team_id == target_id or is_descendant(child, target_id):
                    return True
            return False
            
        if is_descendant(actual_team, target_parent_id):
            return "Error: Cannot migrate a team under its own descendant (would create a cycle)."
            
        success, message = att_manager.negotiate_and_execute_migration(actual_team, target_parent, rationale)
        if success:
            return f"Success: {message}"
        else:
            return f"Error: Migration Rejected: {message}"

    base_tools = {
        "dispatch_subagent": Tool("dispatch_subagent", "Spawns a child AT. Each AT (AI-Team) must have at least 3 Agents. Arguments: task (str), team_purpose (str), member_configs (dict), system_instructions (str), allow_sibling_talk (bool), sibling_talk_rules (str).", dispatch_subagent),
        "delegate_escalation": Tool("delegate_escalation", "Escalates objective upward in the ATT lineage tree with objective (str) and rationale (str).", delegate_escalation),
        "set_sibling_talk": Tool("set_sibling_talk", "Allows parent teams to dynamically set sibling communication permission for their child team. Arguments: child_id (str), allow (bool).", set_sibling_talk),
        "update_team_purpose": Tool("update_team_purpose", "Updates the purpose string of the caller's team. Arguments: new_purpose (str)", update_team_purpose),
        "update_team_status": Tool("update_team_status", "Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)", update_team_status),
        "send_peer_message": Tool("send_peer_message", "Sends a message to a peer team's inbox using their Team ID. Arguments: team_id (str), message (str)", send_peer_message),
        "negotiate_peer_talk": Tool("negotiate_peer_talk", "Requests parents to negotiate a cross-lineage communication channel with a target team. Arguments: target_team_id (str), rationale (str)", negotiate_peer_talk),
        "add_team_member": Tool("add_team_member", "Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)", add_team_member),
        "remove_team_member": Tool("remove_team_member", "Administratively removes a member from a child team. Arguments: team_id (str), agent_name (str)", remove_team_member),
        "request_migration": Tool("request_migration", "Requests to migrate the caller's team to a new parent team in the hierarchy. Arguments: target_parent_id (str), rationale (str)", request_migration)
    }

    if att_manager and att_manager.config.enable_membership_voting:
        base_tools["initiate_membership_vote"] = Tool("initiate_membership_vote", "Initiates a democratic vote to add or remove a team member. Arguments: action (str - 'add' or 'remove'), target (str - role name for 'add', agent name for 'remove'), rationale (str), initiator_type (str - 'individual' or 'AT'), proposed_details (dict - containing 'model', 'role_description', 'system_instructions' if action is 'add')", initiate_membership_vote)
        base_tools["cast_vote"] = Tool("cast_vote", "Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)", cast_vote)
        base_tools["retract_membership_vote"] = Tool("retract_membership_vote", "Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)", retract_membership_vote)

    return base_tools
