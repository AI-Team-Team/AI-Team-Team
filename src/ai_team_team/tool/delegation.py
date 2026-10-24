"""Dynamic delegation, escalation, and AgentTeam status tools."""

from typing import Any, Dict, List, Literal, Optional

from ..core.exceptions import (
    ATTException,
    TeamCreationLimitError,
    ToolArgumentError,
    ToolBusinessError,
    ToolError,
    ToolPermissionError,
)
from .context import _resolve_actual_agent, _resolve_actual_team
from .contract import Tool
from .models import DispatchSubagentArguments


def build_delegation_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def dispatch_subagent(
        task: str,
        team_purpose: str,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_member_ids: Optional[List[str]] = None,
        system_instructions: str = "",
        is_public_visible: bool = False,
        initial_documents: Optional[Dict[str, str]] = None,
        initiator_joins: bool = False,
        unanimous_acceptance_action: Literal[
            "auto_create", "require_confirmation"
        ] = "require_confirmation",
        late_join_policy: Literal[
            "disabled", "open", "require_initiator_confirmation"
        ] = "disabled",
    ) -> dict[str, Any]:
        """Spawns a recursive child AT using new member configs and role-neutral existing Agent IDs."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        
        config = att_manager.config
        if not config.enable_dynamic_delegation:
            raise ToolPermissionError("Dynamic Subagent Delegation is disabled.")
        
        actual_team = _resolve_actual_team(caller_node, att_manager)
        actual_agent = _resolve_actual_agent(caller_node, att_manager)
        if actual_agent is None or actual_team is None:
            raise ToolPermissionError(
                "Dynamic delegation requires an active Agent and AgentTeam invocation."
            )
        
        current_depth = actual_team.depth if actual_team else 1
        max_depth = config.max_delegation_depth
        if current_depth >= max_depth:
            raise ToolBusinessError(
                f"Max delegation depth ({max_depth}) reached; cannot spawn a child AT."
            )

        if existing_member_ids:
            if not isinstance(existing_member_ids, list) or any(
                not isinstance(agent_id, str) or not agent_id
                for agent_id in existing_member_ids
            ):
                raise ToolArgumentError(
                    "existing_member_ids must contain non-empty Agent ID strings."
                )
            if len(existing_member_ids) != len(set(existing_member_ids)):
                raise ToolArgumentError(
                    "existing_member_ids cannot contain duplicate Agent identities."
                )
            unavailable_ids = [
                agent_id
                for agent_id in existing_member_ids
                if agent_id not in att_manager._agents_by_id
                or att_manager._agents_by_id[agent_id].lifecycle_state != "active"
            ]
            if unavailable_ids:
                raise ToolArgumentError(
                    "Existing Agents are not actively registered: "
                    + ", ".join(sorted(unavailable_ids))
                )
        min_size = config.min_subagent_team_size
        if member_configs:
            if not isinstance(member_configs, dict):
                raise ToolArgumentError(
                    "member_configs must map role names to configurations."
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
        if member_configs or existing_member_ids or initiator_joins:
            member_count = (
                len(member_configs or {})
                + len(existing_member_ids or [])
                + int(initiator_joins)
            )
            if member_count < min_size:
                raise ToolArgumentError(
                    f"A delegated AgentTeam MUST have at least {min_size} members."
                )
        else:
            member_count = min_size

        try:
            child = att_manager.create_agent_team(
                creator=actual_team,
                parent=actual_team,
                member_count=member_count,
                system_instructions=system_instructions,
                team_purpose=team_purpose,
                member_configs=member_configs,
                existing_member_ids=existing_member_ids,
                is_public_visible=is_public_visible,
                initial_docs=initial_documents,
                initiating_agent=actual_agent,
                initiator_joins=initiator_joins,
                unanimous_acceptance_action=unanimous_acceptance_action,
                late_join_policy=late_join_policy,
                task=task,
            )
            if hasattr(child, "request_id"):
                return {
                    "status": "PENDING_RESPONSES",
                    "request": child.model_dump(mode="json"),
                    "summary": att_manager.inspect_team_formation(
                        child.request_id, actor=actual_agent
                    ).summary.model_dump(mode="json"),
                }
            return {
                "status": "CREATED",
                "team_id": child.team_id,
                "instruction_message_ids": [
                    f"INITIAL-{child.team_id}-{member.agent_id}" for member in child.members
                ],
                "reason": "Creation is complete; initial instructions do not certify work completion.",
            }
        except (ToolError, ATTException):
            raise
        except TeamCreationLimitError as error:
            raise ToolBusinessError(str(error)) from error
        except (ValueError, TypeError) as error:
            raise ToolArgumentError(str(error)) from error


    async def delegate_escalation(objective: str, rationale: str) -> dict[str, Any]:
        """Ask an actual parent AT through the same configured communication gate."""
        from .context import _resolve_communication_context
        try:
            team, agent = _resolve_communication_context(att_manager)
        except RuntimeError as error:
            raise ToolPermissionError(str(error)) from error
        parent = team.parent_team
        if parent is None:
            raise ToolBusinessError("No explicit parent AgentTeam is available for peer escalation.")
        result = await att_manager.broker.send_peer_message(team, parent, agent.agent_id,
            f"Help requested by AgentTeam {team.team_id}.\nObjective: {objective}\nRationale: {rationale}",
            invocation_id=att_manager._active_tool_invocation_id.get())
        return result.model_dump(mode="json")

    async def update_team_purpose(new_purpose: str) -> str:
        """Updates the purpose string of the caller's team. Arguments: new_purpose (str)"""
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        
        async with actual_team.state_lock:
            with att_manager._topology_lock:
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
            with att_manager._topology_lock:
                actual_team.team_purpose = purpose
                actual_team.team_progress = progress
        att_manager._auto_save(teams={actual_team.team_id})
        return f"Successfully updated team purpose to '{purpose}' and progress to '{progress}'."

    return {
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
                    "existing_member_ids": None,
                    "initiator_joins": False,
                    "unanimous_acceptance_action": "require_confirmation",
                    "late_join_policy": "disabled",
                    "initial_documents": {"brief.md": "Review scope"},
                }
            ],
        ),
        "delegate_escalation": Tool(
            "delegate_escalation",
            "Escalates objective upward in the ATT lineage tree with objective (str) and rationale (str).",
            delegate_escalation,
        ),
        "update_team_purpose": Tool(
            "update_team_purpose",
            "Updates the purpose string of the caller's team. Arguments: new_purpose (str)",
            update_team_purpose,
        ),
        "update_team_status": Tool(
            "update_team_status",
            "Updates the purpose and progress string of the caller's team. Arguments: purpose (str), progress (str)",
            update_team_status,
        ),
    }
