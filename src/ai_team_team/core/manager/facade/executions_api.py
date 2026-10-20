"""Host APIs use an explicit actor; model tools cannot select another owner."""

from typing import Any

from ...agent import Agent
from ...activity.contracts import BackgroundTaskHandle, OperationScope
from ...execution import TaskControlResult, TaskPage, TaskView
from ai_team_team.gated_reader import FileReadResult


class ExecutionAPI:
    def register_executor(self, name: str, executor: Any) -> None:
        self._executions.register_binding(name, executor)

    async def report_execution_health(self, execution_id: str, health: str, evidence_kind: str, evidence: dict | None = None) -> None:
        await self._executions.report_health(execution_id, health, evidence_kind, evidence)

    async def start_background_task(self, tool_name: str, arguments: dict[str, Any], *, actor: Agent,
                                    scope: OperationScope | None = None, description: str = "", labels: tuple[str, ...] = ()) -> BackgroundTaskHandle:
        return await self._executions.start(tool_name, arguments, actor=actor, scope=scope, description=description, labels=labels)

    def list_background_tasks(self, *, actor: Agent, status: str | None = None, query: str | None = None,
                              limit: int = 50, cursor: str | None = None, include_foreground: bool = False) -> TaskPage:
        return self._executions.list(actor=actor, status=status, query=query, limit=limit, cursor=cursor, include_foreground=include_foreground)

    def inspect_background_task(self, execution_id: str, *, actor: Agent) -> TaskView:
        return self._executions.inspect(execution_id, actor=actor)

    async def read_background_task_result(self, execution_id: str, *, actor: Agent, start_line: int = 1,
                                          end_line: int | None = None, start_character: int = 1,
                                          character_count: int | None = None, expected_file_version: str | None = None) -> FileReadResult:
        return await self._executions.read_result(execution_id, actor=actor, start_line=start_line, end_line=end_line,
            start_character=start_character, character_count=character_count, expected_file_version=expected_file_version)

    async def cancel_background_task(self, execution_id: str, *, actor: Agent) -> TaskControlResult:
        return await self._executions.request_cancel(execution_id, actor=actor)

    async def acknowledge_background_task(self, execution_id: str, *, actor: Agent) -> TaskControlResult:
        return await self._executions.acknowledge(execution_id, actor=actor)
