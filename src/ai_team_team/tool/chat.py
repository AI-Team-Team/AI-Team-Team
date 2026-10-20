"""Personal-runtime chat tools; the actor is never a model-supplied argument."""

from typing import Literal, Optional

from ..core.exceptions import ToolPermissionError
from .contract import Tool


def build_chat_tools(manager, *, team_scope=False):
    def actor():
        session = manager._activity.current.get()
        current = manager._active_tool_agent.get()
        if session is None or current is None or session.agent_id != current.agent_id:
            raise ToolPermissionError("Chat tools require the current personal invocation.")
        return manager._messaging.actor(current)

    async def send_team_message(markdown: str, reply_to: Optional[str] = None):
        current = actor()
        team = manager._active_team.get()
        if team is None:
            raise ToolPermissionError("Team publication requires the current AgentTeam scope.")
        return await manager.send_team_message(team.team_id, markdown, actor=current, reply_to=reply_to)

    async def send_direct_message(agent_id: str, markdown: str, reply_to: Optional[str] = None):
        return await manager.send_direct_message(agent_id, markdown, actor=actor(), reply_to=reply_to)

    async def list_team_messages(team_id: str, unread_only: bool = False, query: Optional[str] = None,
                                 limit: int = 50, cursor: Optional[str] = None, include_deleted: bool = False):
        return manager.list_team_messages(team_id, actor=actor(), unread_only=unread_only, query=query,
                                         limit=limit, cursor=cursor, include_deleted=include_deleted)

    async def list_direct_messages(agent_id: str, unread_only: bool = False, query: Optional[str] = None,
                                   limit: int = 50, cursor: Optional[str] = None, include_deleted: bool = False):
        return manager.list_direct_messages(agent_id, actor=actor(), unread_only=unread_only, query=query,
                                           limit=limit, cursor=cursor, include_deleted=include_deleted)

    async def read_chat_message(message_id: str, version: Optional[int] = None, start_line: int = 1,
                                end_line: Optional[int] = None, start_character: int = 1,
                                character_count: Optional[int] = None, expected_file_version: Optional[str] = None):
        return await manager.read_chat_message(message_id, actor=actor(), version=version, start_line=start_line,
            end_line=end_line, start_character=start_character, character_count=character_count,
            expected_file_version=expected_file_version)

    async def edit_chat_message(message_id: str, markdown: str):
        return await manager.edit_chat_message(message_id, markdown, actor=actor())

    async def withdraw_chat_message(message_id: str):
        return await manager.withdraw_chat_message(message_id, actor=actor())

    async def control_chat_message(message_id: str, action: Literal["mark_read", "mark_unread", "delete", "restore"]):
        commands = {"mark_read": "mark_message_read", "mark_unread": "mark_message_unread",
                    "delete": "delete_message", "restore": "restore_message"}
        return await manager.control_chat_message(commands[action], message_id, actor=actor())

    async def set_chat_details(team_details: Optional[bool] = None, direct_details: Optional[bool] = None):
        return await manager.set_chat_details(actor=actor(), team_details=team_details, direct_details=direct_details)

    async def inspect_direct_relationship(agent_id: str):
        return manager.inspect_direct_relationship(agent_id, actor=actor())

    async def list_friendship_requests():
        return {"items": [item.model_dump(mode="json") for item in manager.list_friendship_requests(actor=actor())]}

    async def list_chat_reminders(message_id: Optional[str] = None, limit: int = 50, cursor: Optional[str] = None):
        return manager.list_chat_reminders(actor=actor(), message_id=message_id, limit=limit, cursor=cursor)

    async def request_friendship(agent_id: str):
        return await manager.request_friendship(agent_id, actor=actor())

    async def respond_friendship(request_id: str, decision: Literal["accept", "reject", "ignore", "cancel"]):
        return await manager.respond_friendship(request_id, decision, actor=actor())

    async def control_direct_relationship(agent_id: str, action: Literal["block", "unblock", "remove_friendship", "lift_refusal"]):
        commands = {"block": "block_agent", "unblock": "unblock_agent",
                    "remove_friendship": "remove_friendship", "lift_refusal": "lift_direct_refusal"}
        return await manager.control_direct_relationship(agent_id, commands[action], actor=actor())

    functions = {
        "send_direct_message": (send_direct_message, "Deliberately publishes Markdown to another Agent. A nonfriend has three messages per sender per relationship generation."),
        "list_team_messages": (list_team_messages, "Lists only your eligible live or frozen team history; previews and searches do not mark messages read."),
        "list_direct_messages": (list_direct_messages, "Lists your personal direct conversation with another Agent; previews do not mark read."),
        "read_chat_message": (read_chat_message, "Reads an authorized version with token-bounded Unicode character continuation; only returned content marks this source read."),
        "edit_chat_message": (edit_chat_message, "Publishes a new revision of your own message; current team authority or direct delivery restrictions still apply."),
        "withdraw_chat_message": (withdraw_chat_message, "Replaces your current shared source with a withdrawal marker within the configured window; retained personal evidence is not erased."),
        "control_chat_message": (control_chat_message, "Explicitly marks read/unread, personally hides, or restores your own authorized view; this never changes anybody else's source or view."),
        "set_chat_details": (set_chat_details, "Controls bounded unread previews independently for team and direct chat; counts remain available."),
        "inspect_direct_relationship": (inspect_direct_relationship, "Inspects current friendship, independently owned blocks/refusals, relationship generation, and your remaining stranger allowance."),
        "list_friendship_requests": (list_friendship_requests, "Lists only friendship requests sent to or from you, including historical decisions."),
        "list_chat_reminders": (list_chat_reminders, "Lists only your retained unread captured previews, independently of current withdrawn source bodies; preview inspection does not mark the source read."),
        "request_friendship": (request_friendship, "Sends a metadata-only friendship request; an explicit acceptance is required."),
        "respond_friendship": (respond_friendship, "Accept, reject, or ignore an addressed friendship request, or cancel your own request. Reading mail is never acceptance."),
        "control_direct_relationship": (control_direct_relationship, "Blocks/unblocks your side, removes established friendship, or explicitly lifts your own refusal without altering another Agent's controls."),
    }
    if team_scope:
        functions["send_team_message"] = (send_team_message, "Deliberately publishes Markdown in the captured current AgentTeam; private answers and tool results are never published automatically.")
    read_only = {"list_team_messages", "list_direct_messages", "inspect_direct_relationship", "list_friendship_requests", "list_chat_reminders"}
    tools = {name: Tool(name, description, function,
        result_storage="transient" if name == "read_chat_message" else "protected", execution_contract={
        "effects": ("read_only",) if name in read_only else ("domain_mutation",),
        "background_allowed": False, "required_scope": "agent_team" if name == "send_team_message" else "either",
        "mutation_safety": "managed_lease", "cancellation": "cooperative",
    }) for name, (function, description) in functions.items()}
    for tool in tools.values():
        tool._builtin = True
    return tools
