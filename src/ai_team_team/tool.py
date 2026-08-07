import asyncio
import inspect
import logging
from typing import Dict, Any, Optional, Callable, List, Tuple, Union, Type, get_type_hints

logger = logging.getLogger("ATT.Tools")

def _type_to_schema_type(hint: Any) -> Dict[str, Any]:
    import types
    import typing
    origin = getattr(hint, "__origin__", None)
    
    if origin in {typing.Union, types.UnionType}:
        args = getattr(hint, "__args__", [])
        non_none_args = [a for a in args if a is not type(None) and a is not None]
        if not non_none_args:
            return {"type": "null"}
        if len(non_none_args) == 1:
            return _type_to_schema_type(non_none_args[0])
        else:
            return {"anyOf": [_type_to_schema_type(a) for a in non_none_args]}
            
    if hint is int:
        return {"type": "integer"}
    elif hint is float:
        return {"type": "number"}
    elif hint is bool:
        return {"type": "boolean"}
    elif hint is str:
        return {"type": "string"}
    elif hint is list or origin is list:
        args = getattr(hint, "__args__", [])
        items_schema = {}
        if args:
            items_schema = _type_to_schema_type(args[0])
        return {"type": "array", "items": items_schema}
    elif hint is dict or origin is dict:
        return {"type": "object"}
    
    # Handle nested TypedDicts
    is_td = False
    try:
        from typing import is_typeddict as _is_td
        is_td = _is_td(hint)
    except ImportError:
        pass
    if not is_td:
        is_td = isinstance(hint, type) and hasattr(hint, "__annotations__") and hasattr(hint, "__total__")
    
    if is_td:
        return _schema_from_typeddict(hint, "")
        
    return {"type": "string"}

def _schema_from_typeddict(tp: Any, description: str) -> Dict[str, Any]:
    hints = get_type_hints(tp)
    properties = {}
    required = []
    is_total = getattr(tp, "__total__", True)
    
    for name, hint in hints.items():
        properties[name] = _type_to_schema_type(hint)
        if is_total:
            required.append(name)
            
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "description": description
    }

def _schema_from_function(func: Callable[..., Any], description: str) -> Dict[str, Any]:
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    properties = {}
    required = []
    
    for param_name, param in sig.parameters.items():
        if param_name in ('self', 'cls'):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
            
        param_type = type_hints.get(param_name, Any)
        param_schema = _type_to_schema_type(param_type)
        
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            if param.default is not None:
                param_schema["default"] = param.default
                
        properties[param_name] = param_schema
        
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "description": description
    }

def _schema_from_pydantic(model: Any, description: str) -> Dict[str, Any]:
    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    else:
        schema = model.schema()
    if "description" not in schema or not schema["description"]:
        schema["description"] = description
    return schema

def _resolve_schema(func: Callable[..., Any], description: str, schema_source: Optional[Any] = None) -> Dict[str, Any]:
    if isinstance(schema_source, dict):
        return schema_source
        
    is_pydantic = False
    try:
        from pydantic import BaseModel
        if isinstance(schema_source, type) and issubclass(schema_source, BaseModel):
            is_pydantic = True
    except ImportError:
        pass
        
    if is_pydantic:
        return _schema_from_pydantic(schema_source, description)
        
    is_td = False
    try:
        from typing import is_typeddict as _is_td
        is_td = _is_td(schema_source)
    except ImportError:
        pass
    if not is_td:
        is_td = isinstance(schema_source, type) and hasattr(schema_source, "__annotations__") and hasattr(schema_source, "__total__")
        
    if is_td:
        return _schema_from_typeddict(schema_source, description)
        
    return _schema_from_function(func, description)

class Tool:
    """Encapsulates an AI tool with name, description, and execution logic."""
    def __init__(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None
    ):
        # Resolve positional arguments vs keyword arguments
        if callable(name):
            func = name
            name = getattr(func, "__name__", "custom_tool")
            
        if func is None:
            raise ValueError("A callable function must be provided to create a Tool.")

        if not name:
            name = getattr(func, "__name__", "custom_tool")

        if not description:
            doc = getattr(func, "__doc__", None)
            if doc:
                description = doc.strip().split("\n")[0].strip()
            else:
                description = f"Execute function {name}"

        self.name = name
        self.description = description
        self.func = func
        self.json_schema = _resolve_schema(func, description, schema)

    async def __call__(self, *args, **kwargs) -> str:
        try:
            if inspect.iscoroutinefunction(self.func):
                res = await self.func(*args, **kwargs)
            else:
                res = await asyncio.to_thread(self.func, *args, **kwargs)
            return str(res)
        except Exception as e:
            from .core import ATTException
            if isinstance(e, ATTException):
                raise e
            logger.error(f"Error executing tool '{self.name}': {e}")
            return f"Error executing tool '{self.name}': {e}"

def _resolve_actual_team(caller_node: Any, att_manager: Any) -> Any:
    from .core import Agent, AgentTeam
    if att_manager is not None and hasattr(att_manager, "_active_team"):
        active_team = att_manager._active_team.get()
        if active_team is not None:
            return active_team
    if isinstance(caller_node, AgentTeam):
        return caller_node
    elif isinstance(caller_node, Agent):
        return att_manager.get_agent_team(caller_node)
    return None

def _resolve_actual_agent(caller_node: Any, att_manager: Any) -> Any:
    from .core import Agent

    if isinstance(caller_node, Agent):
        return caller_node
    if att_manager is not None and hasattr(att_manager, "_active_tool_agent"):
        return att_manager._active_tool_agent.get()
    return None

def get_default_tools(context: Dict[str, Any], caller_node: Any) -> Dict[str, Tool]:
    """
    Centralized factory that registers and returns the default set of generic autonomy tools.
    
    Context dictionary requires:
      - 'att_manager': ATTManager (for dynamic spawning and escalations)
    """
    att_manager = context.get("att_manager")

    async def dispatch_subagent(
        task: str,
        team_purpose: str,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        system_instructions: str = "",
        allow_sibling_talk: bool = False,
        sibling_talk_rules: str = "",
        is_public_visible: bool = False,
        initial_documents: Optional[Dict[str, str]] = None
    ) -> str:
        """Spawns a recursive child AT under the ATT tree. Each AT (AI-Team) must have at least 3 Agents. Arguments: task (str), team_purpose (str), member_configs (dict), system_instructions (str), allow_sibling_talk (bool), sibling_talk_rules (str), is_public_visible (bool), initial_documents (dict - mapping file paths to their content strings to be populated in the child team's default DocLib)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        config = att_manager.config
        if not config.enable_dynamic_delegation:
            return "Error: Dynamic Subagent Delegation is disabled in configuration."
        
        from .core import Agent, AgentTeam
        actual_team = _resolve_actual_team(caller_node, att_manager)
        
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
            
            # Validate model names
            for r_name, r_conf in member_configs.items():
                if isinstance(r_conf, dict):
                    model_alias = r_conf.get("model")
                    if model_alias and model_alias != "default":
                        if model_alias not in att_manager.llm_clients and model_alias not in att_manager.model_configs:
                            available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                            return f"Error: Model '{model_alias}' is not registered. Available models are: {available}."
        else:
            member_count = min_size

        try:
            child_team = caller_node.launch_att(
                manager=att_manager,
                member_count=member_count,
                system_instructions=system_instructions,
                team_purpose=team_purpose,
                member_configs=member_configs,
                is_public_visible=is_public_visible,
                initial_docs=initial_documents
            )
            
            # Setup communication rules
            child_team.communication_rules["allow_sibling_talk"] = bool(allow_sibling_talk)
            if sibling_talk_rules:
                child_team.communication_rules["rules"].append(sibling_talk_rules)

            return await att_manager.execute_team_discussion(
                child_team,
                task,
                rounds=config.subagent_discussion_rounds
            )
        except Exception as e:
            return f"Dispatch Subagent Team Error: {e}"


    async def delegate_escalation(objective: str, rationale: str) -> str:
        """Escalates objective upward in the ATT lineage tree. Arguments: objective (str), rationale (str)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
        
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

    async def set_sibling_talk(child_id: str, allow: bool = True) -> str:
        """Sets sibling talk permission for a child team. Arguments: child_id (str), allow (bool)"""
        if not att_manager:
            return "Error: ATTManager not available in tools context."
        
        if child_id not in att_manager.teams:
            return f"Error: Child team '{child_id}' is not registered."
            
        child = att_manager.teams[child_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam for the caller."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{child_id}'."
            
        async with child.state_lock:
            child.communication_rules["allow_sibling_talk"] = bool(allow)
        att_manager._auto_save(teams={child.team_id})
        return f"Successfully set sibling talk for child team '{child_id}' to {allow}."

    async def update_team_purpose(new_purpose: str) -> str:
        """Updates the purpose string of the caller's team. Arguments: new_purpose (str)"""
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        
        async with actual_team.state_lock:
            old_purpose = actual_team.team_purpose
            actual_team.team_purpose = new_purpose
        att_manager._auto_save(teams={actual_team.team_id})
        return f"Successfully updated team purpose from '{old_purpose}' to '{new_purpose}'."

    async def update_team_status(purpose: str, progress: str) -> str:
        """Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)"""
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        
        async with actual_team.state_lock:
            actual_team.team_purpose = purpose
            actual_team.team_progress = progress
        att_manager._auto_save(teams={actual_team.team_id})
        return f"Successfully updated team purpose to '{purpose}' and progress to '{progress}'."

    async def send_peer_message(team_id: str, message: str) -> str:
        """Sends a message to the inbox of a peer team using their Team ID. Arguments: team_id (str), message (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        target = att_manager.teams[team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."

        # Check sibling or peer communication permission
        allowed = await att_manager.broker.negotiate_communication(actual_team, target)
        if not allowed:
            sender_parent = actual_team.parent_team or att_manager.find_parent_team(actual_team)
            recipient_parent = target.parent_team or att_manager.find_parent_team(target)
            if sender_parent == recipient_parent:
                return f"Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk(child_id='{target.team_id}', allow=True) via your parent to request access."
            else:
                return f"Error: Permission Denied. Cross-lineage agreement does not exist. You must call negotiate_peer_talk(target_team_id='{target.team_id}', rationale='...') first to establish a tunnel."
            
        sender_id = actual_team.team_id if actual_team else "Unknown"
        target.receive_message({
            "type": "peer_message",
            "from": sender_id,
            "objective": message
        })
        return f"Message successfully delivered to team '{team_id}'."

    async def negotiate_peer_talk(target_team_id: str, rationale: str, mode: str = None) -> str:
        """Requests parents to negotiate a cross-lineage communication channel with a target team. Arguments: target_team_id (str), rationale (str), mode (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if target_team_id not in att_manager.teams:
            return f"Error: Target team '{target_team_id}' not found."
            
        target = att_manager.teams[target_team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        success = await att_manager.broker.establish_peer_agreement(actual_team, target, rationale, mode)
        if success:
            return f"Success: Cross-lineage peer channel established with team '{target_team_id}'."
        else:
            return f"Negotiation Rejected: Parents could not agree on establishing communication with team '{target_team_id}'."

    async def add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str:
        """Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        child = att_manager.teams[team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{team_id}'."
            
        from .core import Agent
        client = None
        if model_name and model_name != "default":
            if model_name in att_manager.llm_clients:
                client = att_manager.llm_clients[model_name]
            elif model_name in att_manager.model_configs and att_manager.generator_handler:
                from .core import HandlerClientAdapter
                client = HandlerClientAdapter(model_name, att_manager.generator_handler)
                client._supports_native = (
                    att_manager.model_configs.get(model_name, {}).get(
                        "supports_native_tool_calling"
                    )
                    is True
                )
            else:
                available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                return f"Error: Model '{model_name}' is not registered. Available models are: {available}."
        else:
            from .core import ManagerDefaultClientAdapter
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
                return f"Error: Member '{new_agent.name}' already exists."
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
            return "Error: ATTManager not available."
        if team_id not in att_manager.teams:
            return f"Error: Team '{team_id}' not found."
            
        child = att_manager.teams[team_id]
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
                    
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
            
        parent = child.parent_team or att_manager.find_parent_team(child)
        if not parent or parent.team_id != actual_team.team_id:
            return f"Error: Caller team '{actual_team.team_id}' is not the parent of child '{team_id}'."
            
        async with child.state_lock:
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
            return "Error: Membership voting is disabled."
            
        if action == "add" and proposed_details:
            model_name = proposed_details.get("model")
            if model_name and model_name != "default":
                if model_name not in att_manager.llm_clients and model_name not in att_manager.model_configs:
                    available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                    return f"Error: Model '{model_name}' is not registered. Available models are: {available}."

        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        if action not in {"add", "remove"}:
            return "Error: Action must be 'add' or 'remove'."
        if initiator_type not in {"individual", "AT"}:
            return "Error: initiator_type must be 'individual' or 'AT'."
        if initiator_type == "individual":
            if actual_agent is None or actual_agent not in actual_team.members:
                return "Error: Only an active team member can initiate an individual proposal."

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
            return "Error: Membership voting is disabled."
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        if actual_agent is None or actual_agent not in actual_team.members:
            return "Error: Only an active team member can vote."
        caller_agent_name = actual_agent.name
        caller_agent_id = actual_agent.agent_id
        new_agent = None
        membership_changed = False

        async with actual_team.state_lock:
            if proposal_id not in actual_team.proposals:
                return f"Error: Proposal '{proposal_id}' not found."
                
            prop = actual_team.proposals[proposal_id]
            if prop.get("status") != "active":
                return f"Error: Proposal '{proposal_id}' is already closed with status '{prop.get('status')}'."
                
            if vote not in {"Agree", "Disagree", "Abstain"}:
                return "Error: Vote must be 'Agree', 'Disagree', or 'Abstain'."
            if caller_agent_id in prop["votes"]:
                return f"Error: Member '{caller_agent_name}' has already voted."

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
                        result = (
                            f"Error: Proposal '{proposal_id}' was already executed."
                        )
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
                                from .core import HandlerClientAdapter

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
                                    f"Error: Model '{model_name}' is not registered."
                                )
                                client = None
                        else:
                            from .core import ManagerDefaultClientAdapter

                            client = ManagerDefaultClientAdapter(att_manager)
                        if client is not None:
                            from .core import Agent

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
                                    f"Error: Member '{new_agent.name}' already exists."
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
            return "Error: Membership voting is disabled."
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if not actual_team:
            return "Error: Could not resolve the active AgentTeam."
        if actual_agent is None or actual_agent not in actual_team.members:
            return "Error: Only an active team member can retract a proposal."
        caller_agent_name = actual_agent.name
        caller_agent_id = actual_agent.agent_id
            
        async with actual_team.state_lock:
            if proposal_id not in actual_team.proposals:
                return f"Error: Proposal '{proposal_id}' not found."
                
            prop = actual_team.proposals[proposal_id]
            if prop.get("status") != "active":
                return f"Error: Proposal '{proposal_id}' is already closed."
                
            initiator_name = prop.get("initiator_name")
            if (
                prop.get("initiator_type") == "individual"
                and prop.get("initiator_agent_id") != caller_agent_id
            ):
                return f"Error: Only the initiator '{initiator_name}' can retract this proposal."
                
            prop["status"] = "retracted"
        att_manager._auto_save(proposals={actual_team.team_id})
        return f"Successfully retracted proposal '{proposal_id}'."

    async def request_migration(target_parent_id: str, rationale: str) -> str:
        """Requests to migrate the caller's team to a new parent team. Arguments: target_parent_id (str), rationale (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
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
            
        success, message = await att_manager.negotiate_and_execute_migration(actual_team, target_parent, rationale)
        if success:
            return f"Success: {message}"
        else:
            return f"Error: Migration Rejected: {message}"

    async def create_doc_library(name: str, description: str, is_public: bool = False) -> str:
        """Creates a new document library owned by the caller's team. Arguments: name (str), description (str), is_public (bool)"""
        if not att_manager:
            return "Error: ATTManager not available."
        
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
            
        import uuid
        lib_id = f"DL-{uuid.uuid4().hex[:6]}"
        lib = att_manager._new_document_library(
            lib_id=lib_id,
            name=name,
            owner_team_id=caller_team.team_id,
            description=description,
            is_public_visible=is_public,
        )
        att_manager.libraries[lib_id] = lib
        att_manager._auto_save(libraries={lib_id})
        return f"Successfully created document library '{name}' with ID '{lib_id}'."

    async def update_library_metadata(lib_id: str, description: Optional[str] = None, is_public: Optional[bool] = None) -> str:
        """Updates description or visibility of a library owned by the caller's team. Arguments: lib_id (str), description (str, optional), is_public (bool, optional)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            return f"Error: Permission denied. Your team does not own library '{lib_id}'."
            
        if description is not None:
            lib.description = description
        if is_public is not None:
            lib.is_public_visible = is_public
        att_manager._auto_save(libraries={lib_id})
        return f"Successfully updated metadata for library '{lib_id}'."

    async def list_public_libraries() -> str:
        """Lists all document libraries registered as publicly visible. Arguments: none"""
        if not att_manager:
            return "Error: ATTManager not available."
        libs = []
        for lib in att_manager.libraries.values():
            if lib.is_public_visible:
                libs.append(f"- ID: {lib.lib_id} | Name: {lib.name} | Owner: {lib.owner_team_id} | Description: {lib.description}")
        if not libs:
            return "No public document libraries found."
        return "Public Document Libraries:\n" + "\n".join(libs)

    async def grant_library_permission(lib_id: str, path: str, target_team_id: str, permission: str) -> str:
        """Grants permission ('READ' or 'WRITE') to a target team for a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str), permission (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
        if target_team_id not in att_manager.teams:
            return f"Error: Target team '{target_team_id}' not found."
        if permission not in {"READ", "WRITE"}:
            return "Error: Permission must be 'READ' or 'WRITE'."
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            return f"Error: Permission denied. Your team does not own library '{lib_id}'."
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if lib_id not in att_manager.library_permissions:
            att_manager.library_permissions[lib_id] = {}
        if clean_path not in att_manager.library_permissions[lib_id]:
            att_manager.library_permissions[lib_id][clean_path] = {}
            
        att_manager.library_permissions[lib_id][clean_path][target_team_id] = permission
        att_manager._auto_save(permissions={lib_id})
        return f"Successfully granted '{permission}' permission for path '{clean_path}' in library '{lib_id}' to team '{target_team_id}'."

    async def revoke_library_permission(lib_id: str, path: str, target_team_id: str) -> str:
        """Revokes all permissions for a target team under a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            return f"Error: Permission denied. Your team does not own library '{lib_id}'."
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if lib_id in att_manager.library_permissions and clean_path in att_manager.library_permissions[lib_id]:
            if target_team_id in att_manager.library_permissions[lib_id][clean_path]:
                del att_manager.library_permissions[lib_id][clean_path][target_team_id]
                att_manager._auto_save(permissions={lib_id})
                return f"Successfully revoked permissions for path '{clean_path}' in library '{lib_id}' for team '{target_team_id}'."
        return f"No permissions found for path '{clean_path}' in library '{lib_id}' for team '{target_team_id}'."

    async def create_library_link(
        source_lib_id: str,
        source_path: str,
        target_lib_id: str,
        target_path: str,
    ) -> str:
        """Creates an ACL-aware cross-DocLib file link."""
        if not att_manager:
            return "Error: ATTManager not available."
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
        try:
            await att_manager.create_library_link(
                caller_team.team_id,
                source_lib_id,
                source_path,
                target_lib_id,
                target_path,
            )
            return (
                f"Successfully linked '{source_lib_id}:{source_path}' to "
                f"'{target_lib_id}:{target_path}'."
            )
        except Exception as exc:
            return f"Error creating managed library link: {exc}"

    async def write_library_file(lib_id: str, path: str, content: str) -> str:
        """Writes content to a file in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str), content (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            return f"Error: Permission denied. You do not have 'WRITE' permission for path '{path}' in library '{lib_id}'."
            
        try:
            await att_manager.write_library_file(
                caller_team.team_id, lib_id, path, content
            )
            return f"Successfully written file '{path}' in library '{lib_id}'."
        except Exception as e:
            return f"Error writing file '{path}' in library '{lib_id}': {e}"

    async def read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file chunk from a library. Requires 'READ' permission. Arguments: lib_id (str), path (str), start_line (int, default 1), end_line (int, optional)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            return f"Error: Permission denied. You do not have 'READ' permission for path '{path}' in library '{lib_id}'."
            
        try:
            return await att_manager.read_library_file(
                caller_team.team_id,
                lib_id,
                path,
                start_line,
                end_line,
            )
        except Exception as e:
            return f"Error reading file '{path}' in library '{lib_id}': {e}"

    async def delete_library_file(lib_id: str, path: str) -> str:
        """Deletes a file or directory in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str)"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            return f"Error: Permission denied. You do not have 'WRITE' permission for path '{path}' in library '{lib_id}'."
            
        try:
            return await att_manager.delete_library_path(
                caller_team.team_id, lib_id, path
            )
        except Exception as e:
            return f"Error deleting path '{path}' in library '{lib_id}': {e}"

    async def list_library_files(lib_id: str, path: str = "/") -> str:
        """Lists files and directories under a path in a library. Requires 'READ' permission. Arguments: lib_id (str), path (str, default '/')"""
        if not att_manager:
            return "Error: ATTManager not available."
        if lib_id not in att_manager.libraries:
            return f"Error: Document library '{lib_id}' not found."
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            return f"Error: Permission denied. You do not have 'READ' permission for path '{path}' in library '{lib_id}'."
            
        try:
            items = await att_manager.list_library_contents(
                caller_team.team_id, lib_id, path
            )
            if not items:
                return f"Library '{lib_id}' path '{path}' is empty or not a directory."
            return f"Contents of library '{lib_id}' path '{path}':\n" + "\n".join(items)
        except Exception as e:
            return f"Error listing path '{path}' in library '{lib_id}': {e}"

    async def list_private_files(path: str = "/") -> str:
        """Lists the current AI's private files. Arguments: path (str)."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            items = await att_manager.list_private_files(path)
            return "Private workspace is empty." if not items else "\n".join(items)
        except Exception as exc:
            return f"Error listing private files: {exc}"

    async def read_private_file(
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Reads one private file for the current AI."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            return await att_manager.read_private_file(path, start_line, end_line)
        except Exception as exc:
            return f"Error reading private file: {exc}"

    async def write_private_file(path: str, content: str) -> str:
        """Writes one private file for the current AI."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            await att_manager.write_private_file(path, content)
            return f"Successfully wrote private file '{path}'."
        except Exception as exc:
            return f"Error writing private file: {exc}"

    async def delete_private_file(path: str) -> str:
        """Deletes one private file for the current AI."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            return await att_manager.delete_private_file(path)
        except Exception as exc:
            return f"Error deleting private file: {exc}"

    async def move_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one private file for the current AI."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            await att_manager.move_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully moved private file to '{target_path}'."
        except Exception as exc:
            return f"Error moving private file: {exc}"

    async def publish_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Copies one private file into the current team's built-in DocLib."""
        if not att_manager:
            return "Error: ATTManager not available."
        try:
            await att_manager.publish_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully published private file to '{target_path}'."
        except FileExistsError as exc:
            return (
                f"Error publishing private file: {exc} You may rename the "
                "private source, move/rename the team file when you have WRITE "
                "permission on both paths, or retry with overwrite=true."
            )
        except Exception as exc:
            return f"Error publishing private file: {exc}"

    async def move_library_file(
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one normal team-library file with source and target ACL checks."""
        if not att_manager:
            return "Error: ATTManager not available."
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            return "Error: Could not resolve the active AgentTeam."
        try:
            await att_manager.move_library_file(
                caller_team.team_id,
                lib_id,
                source_path,
                target_path,
                overwrite,
            )
            return f"Successfully moved library file to '{target_path}'."
        except Exception as exc:
            return f"Error moving library file: {exc}"

    base_tools = {
        "dispatch_subagent": Tool("dispatch_subagent", "Spawns a child AT. Each AT (AI-Team) must have at least 3 Agents. Arguments: task (str), team_purpose (str), member_configs (dict), system_instructions (str), allow_sibling_talk (bool), sibling_talk_rules (str), is_public_visible (bool), initial_documents (dict - mapping file paths to their content strings to be populated in the child team's default DocLib).", dispatch_subagent),
        "delegate_escalation": Tool("delegate_escalation", "Escalates objective upward in the ATT lineage tree with objective (str) and rationale (str).", delegate_escalation),
        "set_sibling_talk": Tool("set_sibling_talk", "Allows parent teams to dynamically set sibling communication permission for their child team. Arguments: child_id (str), allow (bool).", set_sibling_talk),
        "update_team_purpose": Tool("update_team_purpose", "Updates the purpose string of the caller's team. Arguments: new_purpose (str)", update_team_purpose),
        "update_team_status": Tool("update_team_status", "Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)", update_team_status),
        "send_peer_message": Tool("send_peer_message", "Sends a message to a peer team's inbox using their Team ID. Arguments: team_id (str), message (str)", send_peer_message),
        "negotiate_peer_talk": Tool("negotiate_peer_talk", "Requests parents to negotiate a cross-lineage communication channel with a target team. Arguments: target_team_id (str), rationale (str)", negotiate_peer_talk),
        "add_team_member": Tool("add_team_member", "Administratively adds a new member to a child team. Arguments: team_id (str), role_name (str), model_name (str), role_description (str), system_instructions (str)", add_team_member),
        "remove_team_member": Tool("remove_team_member", "Administratively removes a member from a child team. Arguments: team_id (str), agent_name (str)", remove_team_member),
        "request_migration": Tool("request_migration", "Requests to migrate the caller's team to a new parent team in the hierarchy. Arguments: target_parent_id (str), rationale (str)", request_migration),
        "create_doc_library": Tool("create_doc_library", "Creates a new document library owned by the caller's team. Arguments: name (str), description (str), is_public (bool)", create_doc_library),
        "update_library_metadata": Tool("update_library_metadata", "Updates description or visibility of a library owned by the caller's team. Arguments: lib_id (str), description (str, optional), is_public (bool, optional)", update_library_metadata),
        "list_public_libraries": Tool("list_public_libraries", "Lists all document libraries registered as publicly visible. Arguments: none", list_public_libraries),
        "grant_library_permission": Tool("grant_library_permission", "Grants permission ('READ' or 'WRITE') to a target team for a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str), permission (str)", grant_library_permission),
        "revoke_library_permission": Tool("revoke_library_permission", "Revokes all permissions for a target team under a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str)", revoke_library_permission),
        "create_library_link": Tool("create_library_link", "Creates an ACL-aware file link between registered DocLibs. The caller needs WRITE on the source path and READ on the target path. Arguments: source_lib_id (str), source_path (str), target_lib_id (str), target_path (str)", create_library_link),
        "write_library_file": Tool("write_library_file", "Writes content to a file in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str), content (str)", write_library_file),
        "read_library_file": Tool("read_library_file", "Reads a file chunk from a library. Requires 'READ' permission. Arguments: lib_id (str), path (str), start_line (int, default 1), end_line (int, optional)", read_library_file),
        "delete_library_file": Tool("delete_library_file", "Deletes a file or directory in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str)", delete_library_file),
        "list_library_files": Tool("list_library_files", "Lists files and directories under a path in a library. Requires 'READ' permission. Arguments: lib_id (str), path (str, default '/')", list_library_files),
        "list_private_files": Tool("list_private_files", "Lists files in the current AI's private workspace. Arguments: path (str, default '/')", list_private_files),
        "read_private_file": Tool("read_private_file", "Reads a file from the current AI's private workspace. Arguments: path (str), start_line (int), end_line (int, optional)", read_private_file),
        "write_private_file": Tool("write_private_file", "Writes a file in the current AI's private workspace. Arguments: path (str), content (str)", write_private_file),
        "delete_private_file": Tool("delete_private_file", "Deletes a file from the current AI's private workspace. Arguments: path (str)", delete_private_file),
        "move_private_file": Tool("move_private_file", "Moves a file in the current AI's private workspace. Arguments: source_path (str), target_path (str), overwrite (bool)", move_private_file),
        "publish_private_file": Tool("publish_private_file", "Copies a private file to the current team's built-in DocLib. Arguments: source_path (str), target_path (str), overwrite (bool)", publish_private_file),
        "move_library_file": Tool("move_library_file", "Moves a normal team-library file after source and target WRITE checks. Arguments: lib_id (str), source_path (str), target_path (str), overwrite (bool)", move_library_file)
    }

    if att_manager and att_manager.config.enable_membership_voting:
        base_tools["initiate_membership_vote"] = Tool("initiate_membership_vote", "Initiates a democratic vote to add or remove a team member. Arguments: action (str - 'add' or 'remove'), target (str - role name for 'add', agent name for 'remove'), rationale (str), initiator_type (str - 'individual' or 'AT'), proposed_details (dict - containing 'model', 'role_description', 'system_instructions' if action is 'add')", initiate_membership_vote)
        base_tools["cast_vote"] = Tool("cast_vote", "Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)", cast_vote)
        base_tools["retract_membership_vote"] = Tool("retract_membership_vote", "Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)", retract_membership_vote)

    return base_tools
