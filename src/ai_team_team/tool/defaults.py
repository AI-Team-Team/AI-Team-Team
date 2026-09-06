"""Default ATT tool registry composition."""

from typing import Any, Dict

from .communication import build_communication_tools
from .contract import Tool
from .delegation import build_delegation_tools
from .libraries import build_library_tools
from .membership import build_membership_tools
from .memory import build_memory_tools
from .migration import build_migration_tools


def get_default_tools(context: Dict[str, Any], caller_node: Any) -> Dict[str, Tool]:
    """Builds the default invocation-bound ATT tool registry."""
    att_manager = context.get("att_manager")

    tools: Dict[str, Tool] = {}
    tools.update(build_delegation_tools(att_manager, caller_node))
    tools.update(build_communication_tools(att_manager, caller_node))

    membership_tools = build_membership_tools(att_manager, caller_node)
    tools["add_team_member"] = membership_tools["add_team_member"]
    tools["remove_team_member"] = membership_tools["remove_team_member"]

    tools.update(build_migration_tools(att_manager, caller_node))
    tools.update(build_library_tools(att_manager, caller_node))
    tools.update(build_memory_tools(att_manager))

    tools["initiate_membership_vote"] = membership_tools["initiate_membership_vote"]
    tools["cast_vote"] = membership_tools["cast_vote"]
    tools["retract_membership_vote"] = membership_tools["retract_membership_vote"]
    return tools
