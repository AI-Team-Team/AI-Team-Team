"""Dynamic delegation, escalation, and AgentTeam status tools."""

from typing import Any, Dict, Optional

from ..core.exceptions import (
    ATTException,
    ToolArgumentError,
    ToolBusinessError,
    ToolError,
    ToolPermissionError,
)
from .context import _resolve_actual_team
from .contract import Tool
from .models import DispatchSubagentArguments


def build_delegation_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
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
        
        from ..core import Agent, AgentTeam
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

