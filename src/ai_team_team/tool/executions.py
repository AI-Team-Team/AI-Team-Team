"""Task tools resolve owner and scope from the current personal invocation."""

from typing import Any, Optional

from ..core.activity.contracts import ToolExecutionContract
from ..core.exceptions import ToolPermissionError, ToolArgumentError, ToolBusinessError
from ..gated_reader import FileReadError, FileReadRangeError
from .contract import Tool


def build_execution_tools(manager):
    service = manager._executions

    def owner():
        session = manager._activity.current.get()
        actor = manager._active_tool_agent.get()
        if session is None or actor is None or session.agent_id != actor.agent_id:
            raise ToolPermissionError("Task tools require the current personal invocation.")
        return service.actor(actor)

    async def start_background_task(tool_name: str, arguments: dict[str, Any], description: str = "", labels: Optional[list[str]] = None):
        return await service.start(tool_name, arguments, actor=owner(), description=description, labels=labels or ())

    def list_background_tasks(status: Optional[str] = None, limit: int = 50, cursor: Optional[str] = None):
        return service.list(actor=owner(), status=status, limit=limit, cursor=cursor)

    def search_background_tasks(query: str, status: Optional[str] = None, limit: int = 50, cursor: Optional[str] = None):
        return service.list(actor=owner(), status=status, query=query, limit=limit, cursor=cursor)

    def inspect_background_task(execution_id: str):
        return service.inspect(execution_id, actor=owner())

    async def read_background_task_result(execution_id: str, start_line: int = 1, end_line: Optional[int] = None,
                                         start_character: int = 1, character_count: Optional[int] = None,
                                         expected_file_version: Optional[str] = None):
        try:
            return await service.read_result(execution_id, actor=owner(), start_line=start_line, end_line=end_line,
                start_character=start_character, character_count=character_count, expected_file_version=expected_file_version)
        except FileReadRangeError as error:
            raise ToolArgumentError(str(error), error_kind=error.error_kind) from error
        except FileReadError as error:
            raise ToolBusinessError(str(error), error_kind=error.error_kind) from error

    async def cancel_background_task(execution_id: str):
        return await service.request_cancel(execution_id, actor=owner())

    async def acknowledge_background_task(execution_id: str):
        return await service.acknowledge(execution_id, actor=owner())

    functions = (start_background_task, list_background_tasks, search_background_tasks, inspect_background_task,
                 read_background_task_result, cancel_background_task, acknowledge_background_task)
    tools = {function.__name__: Tool(function, description={
        "start_background_task": "Admits one available, explicitly background-allowed tool under your current scope; returns its durable task reference without waiting for completion.",
        "list_background_tasks": "Lists your tasks across memberships; metadata inspection is not attention acknowledgement.",
        "search_background_tasks": "Searches only your task metadata, without searching protected output bodies.",
        "inspect_background_task": "Inspects your execution, health, attention, and uncertainty separately; contains no result body.",
        "read_background_task_result": "Explicitly reads a token-bounded result with Unicode character continuation; reading does not acknowledge attention.",
        "cancel_background_task": "Requests stopping your execution; a request or timeout is not proof that an external operation stopped.",
        "acknowledge_background_task": "Acknowledges attention without changing outcome, deleting history, or reading a message.",
    }[function.__name__], result_storage="transient" if function.__name__ == "read_background_task_result" else "protected",
        execution_contract=ToolExecutionContract(
        effects=("read_only",) if function.__name__ in {"list_background_tasks", "search_background_tasks", "inspect_background_task", "read_background_task_result"} else ("domain_mutation",),
        background_allowed=False, required_scope="personal", mutation_safety="managed_lease")) for function in functions}
    for tool in tools.values():
        tool._builtin = True
    return tools
