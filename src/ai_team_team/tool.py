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
        member_count: int = 3,
        roles_and_models: Optional[Dict[str, str]] = None,
        system_instructions: str = ""
    ) -> str:
        """Spawns a recursive child AT under the ATT tree to execute a specialized task. Arguments: task (str), team_purpose (str), member_count (int), roles_and_models (dict), system_instructions (str)"""
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

        try:
            member_count = int(member_count)
            min_size = config.min_subagent_team_size
            if member_count < min_size:
                return f"Error: A valid Agent Team MUST have at least {min_size} members. Please reconsider your team design and try again."
        except ValueError:
            return "Error: member_count must be an integer."
        
        try:
            roles_and_presets = []
            if roles_and_models:
                for role_name, _ in roles_and_models.items():
                    roles_and_presets.append((f"Dynamic_{role_name}", role_name))
            else:
                preset = att_manager.get_preset("generic")
                roles_and_presets = preset.get("roles", [])

            child_team = caller_node.launch_att(
                manager=att_manager,
                member_count=member_count,
                roles_and_presets=roles_and_presets,
                system_instructions=system_instructions,
                team_purpose=team_purpose
            )
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
                    
        sender_id = actual_team.team_id if actual_team else "Unknown"
        target.receive_message({
            "type": "peer_message",
            "from": sender_id,
            "objective": message
        })
        return f"Message successfully delivered to team '{team_id}'."

    return {
        "dispatch_subagent": Tool("dispatch_subagent", "Spawns a child AT. Arguments: task (str), team_purpose (str), member_count (int), roles_and_models (dict), system_instructions (str).", dispatch_subagent),
        "delegate_escalation": Tool("delegate_escalation", "Escalates objective upward in the ATT lineage tree with objective (str) and rationale (str).", delegate_escalation),
        "set_sibling_talk": Tool("set_sibling_talk", "Allows parent teams to dynamically set sibling communication permission for their child team. Arguments: child_id (str), allow (bool).", set_sibling_talk),
        "update_team_purpose": Tool("update_team_purpose", "Updates the purpose string of the caller's team. Arguments: new_purpose (str)", update_team_purpose),
        "send_peer_message": Tool("send_peer_message", "Sends a message to a peer team's inbox using their Team ID. Arguments: team_id (str), message (str)", send_peer_message)
    }
