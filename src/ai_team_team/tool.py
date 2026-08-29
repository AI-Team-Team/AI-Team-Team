import asyncio
import inspect
import json
import logging
import types
import typing
from collections.abc import Mapping
from typing import Annotated, Dict, Any, Optional, Callable, List, Tuple, Union, Type, get_type_hints

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PydanticUserError,
    TypeAdapter,
    ValidationError,
    create_model,
    model_validator,
)

from .core.exceptions import (
    ATTException,
    RetryableToolError,
    ToolArgumentError,
    ToolBusinessError,
    ToolError,
    ToolPermissionError,
)

logger = logging.getLogger("ATT.Tools")


class DispatchMemberConfig(BaseModel):
    """Strict model-visible configuration for one delegated Agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    hire_agent: Optional[str] = None
    role_description: str = ""
    system_instructions: str = ""

    @model_validator(mode="after")
    def validate_source(self):
        if self.model and self.hire_agent:
            raise ValueError("model and hire_agent are mutually exclusive.")
        return self


class DispatchSubagentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: str
    team_purpose: str
    member_configs: Optional[Dict[str, DispatchMemberConfig]] = None
    system_instructions: str = ""
    is_public_visible: bool = False
    initial_documents: Optional[Dict[str, str]] = None


class MembershipProposalDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    role_description: str = ""
    system_instructions: str = ""


class MembershipProposalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: str
    target: str
    rationale: str
    initiator_type: str = "individual"
    proposed_details: Optional[MembershipProposalDetails] = None


def _schema_from_typeddict(tp: Any, description: str) -> Dict[str, Any]:
    schema = TypeAdapter(tp).json_schema()
    schema["additionalProperties"] = False
    schema["description"] = description
    return schema


def _schema_from_function(func: Callable[..., Any], description: str) -> Dict[str, Any]:
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    fields = {}
    for param_name, param in sig.parameters.items():
        if param_name in ('self', 'cls'):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
            
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (type_hints.get(param_name, Any), default)
    model = create_model(
        f"{getattr(func, '__name__', 'Tool')}Arguments",
        __config__=ConfigDict(extra="forbid", strict=True),
        **fields,
    )
    schema = model.model_json_schema()
    schema["description"] = description
    return schema

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

    name: str
    description: str
    func: Callable[..., Any]
    schema_source: Optional[Any]
    json_schema: Dict[str, Any]
    prompt_schema_mode: Optional[str]
    examples: List[Dict[str, Any]]
    retry_safe: bool

    def __init__(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None,
        *,
        prompt_schema_mode: Optional[str] = None,
        examples: Optional[List[Dict[str, Any]]] = None,
        retry_safe: bool = False,
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
        self.schema_source = schema
        try:
            self.json_schema = _resolve_schema(func, description, schema)
        except PydanticUserError as exc:
            if exc.code == "typed-dict-version":
                raise ValueError(
                    f"Tool {name!r} uses typing.TypedDict, which Pydantic does not support "
                    "before Python 3.12. Import TypedDict, Required, and NotRequired "
                    "from typing_extensions."
                ) from exc
            raise
        try:
            Draft202012Validator.check_schema(self.json_schema)
        except SchemaError as exc:
            raise ValueError(f"Invalid JSON Schema for tool {name!r}: {exc}") from exc
        if prompt_schema_mode not in {
            None,
            "compact",
            "full",
            "compact_with_examples",
        }:
            raise ValueError("Invalid tool prompt schema mode.")
        if not isinstance(retry_safe, bool):
            raise ValueError("retry_safe must be a boolean.")
        self.prompt_schema_mode = prompt_schema_mode
        self.examples = list(examples or [])
        self.retry_safe = retry_safe
        self._signature = inspect.signature(func)
        try:
            self._type_hints = get_type_hints(func)
        except (NameError, TypeError):
            self._type_hints = {}
        self._json_validator = Draft202012Validator(self.json_schema)

    def validate_arguments(
        self, args: List[Any], kwargs: Dict[str, Any]
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Strictly validates one invocation before any tool code runs."""
        try:
            bound = self._signature.bind(*args, **kwargs)
        except TypeError as exc:
            raise ToolArgumentError(str(exc)) from exc

        mapping = dict(bound.arguments)
        raw_mapping = dict(mapping)
        try:
            if isinstance(self.schema_source, type) and issubclass(
                self.schema_source, BaseModel
            ):
                validated = self.schema_source.model_validate_json(
                    json.dumps(mapping), strict=True
                )
                mapping = validated.model_dump(
                    mode="python", exclude_unset=True
                )
            elif self.schema_source is not None and typing.is_typeddict(
                self.schema_source
            ):
                mapping = TypeAdapter(self.schema_source).validate_json(
                    json.dumps(mapping), strict=True
                )
            else:
                for name, value in list(mapping.items()):
                    hint = self._type_hints.get(name, Any)
                    if hint is not Any:
                        mapping[name] = TypeAdapter(hint).validate_json(
                            json.dumps(value), strict=True
                        )
            self._json_validator.validate(raw_mapping)
        except (
            ValidationError,
            JSONSchemaValidationError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ToolArgumentError(str(exc)) from exc

        for name, value in mapping.items():
            bound.arguments[name] = value
        return list(bound.args), dict(bound.kwargs)

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        checked_args, checked_kwargs = self.validate_arguments(
            list(args), dict(kwargs)
        )
        return await self.invoke_validated(*checked_args, **checked_kwargs)

    async def invoke_validated(self, *args: Any, **kwargs: Any) -> Any:
        """Invokes a callable after the shared executor has validated input."""
        if inspect.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        return await asyncio.to_thread(
            self.func, *args, **kwargs
        )

    @staticmethod
    def serialize_result(res: Any) -> str:
        if isinstance(res, BaseModel):
            return res.model_dump_json()
        if isinstance(res, Mapping):
            return json.dumps(dict(res), sort_keys=True)
        return str(res)

    async def __call__(self, *args, **kwargs) -> str:
        try:
            return self.serialize_result(await self.invoke(*args, **kwargs))
        except ToolError as exc:
            return f"Error: {exc}"
        except Exception as e:
            if isinstance(e, ATTException):
                raise e
            logger.error(f"Error executing tool '{self.name}': {e}")
            return f"Error executing tool '{self.name}': {e}"


def _resolve_schema_ref(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return schema
    return root.get("$defs", {}).get(ref.rsplit("/", 1)[-1], schema)


def _compact_schema_type(schema: Dict[str, Any], root: Dict[str, Any]) -> str:
    schema = _resolve_schema_ref(schema, root)
    if "anyOf" in schema:
        return " | ".join(
            _compact_schema_type(item, root) for item in schema["anyOf"]
        )
    if "enum" in schema:
        return "literal[" + ", ".join(repr(v) for v in schema["enum"]) + "]"
    value_type = schema.get("type", "any")
    if value_type == "array":
        return f"list[{_compact_schema_type(schema.get('items', {}), root)}]"
    if value_type == "object":
        properties = schema.get("properties", {})
        if properties:
            required = set(schema.get("required", []))
            fields = []
            for name, child in properties.items():
                marker = "" if name in required else "?"
                fields.append(
                    f"{name}{marker}: {_compact_schema_type(child, root)}"
                )
            return "{" + ", ".join(fields) + "}"
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_compact_schema_type(additional, root)}]"
        return "dict"
    return str(value_type)


def render_tool_prompt(tool: Tool, mode: str) -> str:
    """Renders one tool contract for a Text ReAct system prompt."""
    schema = tool.json_schema
    if mode == "full":
        rendered = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    else:
        required = set(schema.get("required", []))
        parts = []
        for name, child in schema.get("properties", {}).items():
            marker = "required" if name in required else "optional"
            default = (
                f", default={child['default']!r}"
                if "default" in child
                else ""
            )
            parts.append(
                f"{name}: {_compact_schema_type(child, schema)} ({marker}{default})"
            )
        rendered = "; ".join(parts) if parts else "no arguments"
    line = f"- **{tool.name}**: {tool.description}\n  Schema: {rendered}"
    if mode == "compact_with_examples" and tool.examples:
        line += "\n  Examples: " + json.dumps(
            tool.examples, ensure_ascii=False, sort_keys=True
        )
    elif mode == "full" and tool.examples:
        line += "\n  Examples: " + json.dumps(
            tool.examples, ensure_ascii=False, sort_keys=True
        )
    return line

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

    if att_manager is not None and hasattr(att_manager, "_active_tool_agent"):
        active_agent = att_manager._active_tool_agent.get()
        if active_agent is not None:
            return active_agent
    if isinstance(caller_node, Agent):
        return caller_node
    return None


def _resolve_communication_context(att_manager: Any) -> Tuple[Any, Any]:
    """Resolves a fail-closed invocation-scoped AgentTeam and actor Agent."""
    if att_manager is None:
        raise RuntimeError("ATTManager is not available.")
    team = att_manager._active_team.get()
    agent = att_manager._active_tool_agent.get()
    if team is None or agent is None:
        raise RuntimeError(
            "Peer communication requires an active AgentTeam invocation context."
        )
    if att_manager.teams.get(team.team_id) is not team:
        raise RuntimeError("The active AgentTeam is not registered.")
    if (
        att_manager._agents_by_id.get(agent.agent_id) is not agent
        or agent.lifecycle_state != "active"
        or all(member.agent_id != agent.agent_id for member in team.members)
    ):
        raise RuntimeError(
            "The active Agent is not an active member of the current AgentTeam."
        )
    return team, agent

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
        is_public_visible: bool = False,
        initial_documents: Optional[Dict[str, str]] = None
    ) -> str:
        """Spawns a recursive child AT under the ATT tree. Arguments: task, team_purpose, member_configs, system_instructions, is_public_visible, initial_documents."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        
        config = att_manager.config
        if not config.enable_dynamic_delegation:
            raise ToolPermissionError("Dynamic Subagent Delegation is disabled.")
        
        from .core import Agent, AgentTeam
        actual_team = _resolve_actual_team(caller_node, att_manager)
        
        current_depth = actual_team.depth if actual_team else 1
        max_depth = config.max_delegation_depth
        if current_depth >= max_depth:
            raise ToolBusinessError(
                f"Max delegation depth ({max_depth}) reached; cannot spawn a child AT."
            )

        min_size = config.min_subagent_team_size
        if member_configs:
            if not isinstance(member_configs, dict):
                raise ToolArgumentError(
                    "member_configs must map role names to configurations."
                )
            member_count = len(member_configs)
            if member_count < min_size:
                raise ToolArgumentError(
                    f"A delegated AgentTeam MUST have at least {min_size} members."
                )
            
            # Validate model names
            for r_name, r_conf in member_configs.items():
                if isinstance(r_conf, dict):
                    model_alias = r_conf.get("model")
                    if model_alias and model_alias != "default":
                        if model_alias not in att_manager.llm_clients and model_alias not in att_manager.model_configs:
                            available = list(att_manager.model_configs.keys()) + list(att_manager.llm_clients.keys())
                            raise ToolArgumentError(
                                f"Model {model_alias!r} is not registered. Available models: {available}."
                            )
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
            
            return await att_manager.execute_team_discussion(
                child_team,
                task,
                rounds=config.subagent_discussion_rounds
            )
        except (ToolError, ATTException):
            raise
        except Exception as e:
            raise ToolBusinessError(f"Dispatch failed: {e}") from e


    async def delegate_escalation(objective: str, rationale: str) -> str:
        """Escalates objective upward in the ATT lineage tree. Arguments: objective (str), rationale (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
        
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")

        parent = actual_team.parent_team or att_manager.find_parent_team(actual_team)
        if not parent:
            raise ToolBusinessError("No parent AgentTeam exists for escalation.")
        
        try:
            payload = {
                "type": "escalation_spawn",
                "objective": objective,
                "rationale": rationale,
                "from": actual_team.team_id
            }
            parent.receive_message(payload)
            return f"Escalation successfully dispatched to parent team '{parent.team_id}'."
        except (ToolError, ATTException):
            raise
        except Exception as e:
            raise ToolBusinessError(f"Escalation failed: {e}") from e

    async def update_team_purpose(new_purpose: str) -> str:
        """Updates the purpose string of the caller's team. Arguments: new_purpose (str)"""
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        
        async with actual_team.state_lock:
            old_purpose = actual_team.team_purpose
            actual_team.team_purpose = new_purpose
        att_manager._auto_save(teams={actual_team.team_id})
        return f"Successfully updated team purpose from '{old_purpose}' to '{new_purpose}'."

    async def update_team_status(purpose: str, progress: str) -> str:
        """Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)"""
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        
        async with actual_team.state_lock:
            actual_team.team_purpose = purpose
            actual_team.team_progress = progress
        att_manager._auto_save(teams={actual_team.team_id})
        return f"Successfully updated team purpose to '{purpose}' and progress to '{progress}'."

    async def send_peer_message(team_id: str, message: str) -> str:
        """Sends a message through the ATT-configured communication regime."""
        try:
            actual_team, actual_agent = _resolve_communication_context(
                att_manager
            )
        except RuntimeError as exc:
            return json.dumps(
                {"status": "NO_AGREEMENT", "reason": str(exc)},
                sort_keys=True,
            )
        if team_id not in att_manager.teams:
            return json.dumps(
                {"status": "NO_AGREEMENT", "reason": f"Unknown AgentTeam {team_id!r}."}
            )
        target = att_manager.teams[team_id]
        result = await att_manager.broker.send_peer_message(
            actual_team,
            target,
            actual_agent.agent_id,
            message,
            invocation_id=att_manager._active_tool_invocation_id.get(),
        )
        return result.model_dump_json()

    async def request_peer_communication(
        team_id: str, rationale: str
    ) -> str:
        """Requests a persistent channel under ATT communication policy."""
        try:
            actual_team, actual_agent = _resolve_communication_context(
                att_manager
            )
        except RuntimeError as exc:
            return json.dumps(
                {"status": "DENIED", "reason": str(exc)}, sort_keys=True
            )
        if team_id not in att_manager.teams:
            return json.dumps(
                {"status": "DENIED", "reason": f"Unknown AgentTeam {team_id!r}."}
            )
        result = await att_manager.broker.request_peer_communication(
            actual_team,
            att_manager.teams[team_id],
            actual_agent.agent_id,
            rationale,
        )
        return result.model_dump_json()

    async def revoke_peer_agreement(
        agreement_id: str, reason: str
    ) -> str:
        """Revokes a channel when the current AgentTeam is an endpoint."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        result = await att_manager.broker.revoke_agreement(
            agreement_id, actual_team.team_id, reason
        )
        return result.model_dump_json()

    async def list_peer_requests(status: str = "pending") -> str:
        """Lists communication requests visible to the current AgentTeam."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        normalized = status.upper()
        rows = []
        for request in att_manager.broker.communication_requests.values():
            is_endpoint = actual_team.team_id in {
                request.sender_team_id,
                request.recipient_team_id,
            }
            is_approver = any(
                principal.kind == "agent_team"
                and principal.principal_id == actual_team.team_id
                for principal in request.approval_principals
            )
            if not (is_endpoint or is_approver):
                continue
            if normalized not in {"ALL", request.status.value}:
                continue
            rows.append(request.model_dump(mode="json"))
        return json.dumps(rows, sort_keys=True)

    async def list_peer_agreements(active_only: bool = True) -> str:
        """Lists agreements whose endpoint is the current AgentTeam."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        rows = [
            agreement.model_dump(mode="json")
            for agreement in att_manager.broker.agreements.values()
            if actual_team.team_id
            in {agreement.source_team_id, agreement.target_team_id}
            and (agreement.active or not active_only)
        ]
        return json.dumps(rows, sort_keys=True)

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
                raise ToolArgumentError(
                    f"Model {model_name!r} is not registered. Available models: {available}."
                )
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
                                    f"Proposal '{proposal_id}' failed execution because model {model_name!r} is not registered."
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

    async def request_migration(target_parent_id: str, rationale: str) -> str:
        """Requests to migrate the caller's team to a new parent team. Arguments: target_parent_id (str), rationale (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if target_parent_id not in att_manager.teams:
            raise ToolBusinessError(
                f"Target parent AgentTeam {target_parent_id!r} was not found."
            )
            
        target_parent = att_manager.teams[target_parent_id]
        if target_parent_id == actual_team.team_id:
            raise ToolBusinessError("An AgentTeam cannot become its own parent.")
            
        def is_descendant(t, target_id):
            for child in t.child_teams:
                if child.team_id == target_id or is_descendant(child, target_id):
                    return True
            return False
            
        if is_descendant(actual_team, target_parent_id):
            raise ToolBusinessError(
                "An AgentTeam cannot migrate under its own descendant because that would create a cycle."
            )
            
        success, message = await att_manager.negotiate_and_execute_migration(actual_team, target_parent, rationale)
        if success:
            return f"Success: {message}"
        raise ToolBusinessError(f"Migration was rejected: {message}")

    async def create_doc_library(name: str, description: str, is_public: bool = False) -> str:
        """Creates a new document library owned by the caller's team. Arguments: name (str), description (str), is_public (bool)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
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
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        if description is not None:
            lib.description = description
        if is_public is not None:
            lib.is_public_visible = is_public
        att_manager._auto_save(libraries={lib_id})
        return f"Successfully updated metadata for library '{lib_id}'."

    async def list_public_libraries() -> str:
        """Lists all document libraries registered as publicly visible. Arguments: none"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
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
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
        if target_team_id not in att_manager.teams:
            raise ToolBusinessError(f"Target AgentTeam {target_team_id!r} was not found.")
        if permission not in {"READ", "WRITE"}:
            raise ToolArgumentError("permission must be 'READ' or 'WRITE'.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
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
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
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
            raise ToolBusinessError("ATTManager is not available in tools context.")
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
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
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Managed library link creation failed: {exc}"
            ) from exc

    async def write_library_file(lib_id: str, path: str, content: str) -> str:
        """Writes content to a file in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str), content (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            raise ToolPermissionError(
                f"Permission denied: WRITE permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            await att_manager.write_library_file(
                caller_team.team_id, lib_id, path, content
            )
            return f"Successfully written file '{path}' in library '{lib_id}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Writing path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file chunk from a library. Requires 'READ' permission. Arguments: lib_id (str), path (str), start_line (int, default 1), end_line (int, optional)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            raise ToolPermissionError(
                f"Permission denied: READ permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            content = await att_manager.read_library_file(
                caller_team.team_id,
                lib_id,
                path,
                start_line,
                end_line,
            )
            if content.startswith("Error: "):
                raise ToolBusinessError(content.removeprefix("Error: "))
            return content
        except ToolError:
            raise
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Reading path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def delete_library_file(lib_id: str, path: str) -> str:
        """Deletes a file or directory in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            raise ToolPermissionError(
                f"Permission denied: WRITE permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            result = await att_manager.delete_library_path(
                caller_team.team_id, lib_id, path
            )
            if result.startswith("Error: "):
                raise ToolBusinessError(result.removeprefix("Error: "))
            return result
        except ToolError:
            raise
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Deleting path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def list_library_files(lib_id: str, path: str = "/") -> str:
        """Lists files and directories under a path in a library. Requires 'READ' permission. Arguments: lib_id (str), path (str, default '/')"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            raise ToolPermissionError(
                f"Permission denied: READ permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            items = await att_manager.list_library_contents(
                caller_team.team_id, lib_id, path
            )
            if not items:
                return f"Library '{lib_id}' path '{path}' is empty or not a directory."
            return f"Contents of library '{lib_id}' path '{path}':\n" + "\n".join(items)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Listing path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def list_private_files(path: str = "/") -> str:
        """Lists the current AI's private files. Arguments: path (str)."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            items = await att_manager.list_private_files(path)
            return "Private workspace is empty." if not items else "\n".join(items)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file listing failed.") from exc

    async def read_private_file(
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Reads one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            return await att_manager.read_private_file(path, start_line, end_line)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file reading failed.") from exc

    async def write_private_file(path: str, content: str) -> str:
        """Writes one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.write_private_file(path, content)
            return f"Successfully wrote private file '{path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file writing failed.") from exc

    async def delete_private_file(path: str) -> str:
        """Deletes one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            return await att_manager.delete_private_file(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file deletion failed.") from exc

    async def move_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.move_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully moved private file to '{target_path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file move failed.") from exc

    async def publish_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Copies one private file into the current team's built-in DocLib."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.publish_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully published private file to '{target_path}'."
        except FileExistsError as exc:
            raise ToolBusinessError(
                f"The publication target already exists: {exc}. Rename the private source, move or rename the team file with WRITE permission on both paths, or retry with overwrite=true."
            ) from exc
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file publication failed.") from exc

    async def move_library_file(
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one normal team-library file with source and target ACL checks."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        try:
            await att_manager.move_library_file(
                caller_team.team_id,
                lib_id,
                source_path,
                target_path,
                overwrite,
            )
            return f"Successfully moved library file to '{target_path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Library file move failed: {exc}"
            ) from exc

    base_tools = {
        "dispatch_subagent": Tool(
            "dispatch_subagent",
            "Spawns a child AT with validated member and initial document configuration.",
            dispatch_subagent,
            schema=DispatchSubagentArguments,
            prompt_schema_mode="full",
            examples=[
                {
                    "task": "Verify the proposed design.",
                    "team_purpose": "Independent design review",
                    "member_configs": {
                        "Reviewer": {
                            "model": "default",
                            "role_description": "Review correctness.",
                        },
                        "Tester": {"model": "default"},
                        "Arbitrator": {"model": "default"},
                    },
                    "initial_documents": {"brief.md": "Review scope"},
                }
            ],
        ),
        "delegate_escalation": Tool("delegate_escalation", "Escalates objective upward in the ATT lineage tree with objective (str) and rationale (str).", delegate_escalation),
        "update_team_purpose": Tool("update_team_purpose", "Updates the purpose string of the caller's team. Arguments: new_purpose (str)", update_team_purpose),
        "update_team_status": Tool("update_team_status", "Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)", update_team_status),
        "send_peer_message": Tool("send_peer_message", "Sends a message to a peer team's inbox using their Team ID. Arguments: team_id (str), message (str)", send_peer_message),
        "request_peer_communication": Tool("request_peer_communication", "Requests a persistent peer communication channel. Arguments: team_id (str), rationale (str)", request_peer_communication),
        "revoke_peer_agreement": Tool("revoke_peer_agreement", "Revokes an endpoint communication agreement. Arguments: agreement_id (str), reason (str)", revoke_peer_agreement),
        "list_peer_requests": Tool("list_peer_requests", "Lists communication requests visible to the current AgentTeam. Arguments: status (str)", list_peer_requests),
        "list_peer_agreements": Tool("list_peer_agreements", "Lists communication agreements visible to the current AgentTeam. Arguments: active_only (bool)", list_peer_agreements),
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

    base_tools["initiate_membership_vote"] = Tool(
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
    )
    base_tools["cast_vote"] = Tool("cast_vote", "Casts a ballot on an active proposal. Arguments: proposal_id (str), vote (str - 'Agree', 'Disagree', or 'Abstain'), public (bool), rationale (str)", cast_vote)
    base_tools["retract_membership_vote"] = Tool("retract_membership_vote", "Withdraws an active proposal. Only the initiator can retract. Arguments: proposal_id (str)", retract_membership_vote)

    return base_tools
