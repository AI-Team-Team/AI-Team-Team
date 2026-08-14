import asyncio
import inspect
from typing import Any, Dict, List, Mapping, Optional

from .exceptions import (
    ATTException,
    RetryableToolError,
    ToolArgumentError,
    ToolBusinessError,
    ToolPermissionError,
)
from .response import ToolResult, ToolResultStatus


class ToolExecutor:
    """Executes Text and Native tool calls through one classified runtime."""

    def __init__(self, team: Any, agent: Any, manager: Any) -> None:
        self.team = team
        self.agent = agent
        self.manager = manager

    async def execute(
        self,
        tool_name: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        *,
        call_id: str = "",
        raw: Any = None,
        tools: Optional[Mapping[str, Any]] = None,
    ) -> ToolResult:
        registry = tools if tools is not None else self.team.tools
        tool = registry.get(tool_name)
        if tool is None:
            return ToolResult(
                call_id,
                tool_name,
                f"Tool {tool_name!r} is not available in this invocation.",
                raw,
                status=ToolResultStatus.UNKNOWN_TOOL,
                error_kind="unknown_tool",
            )

        active_agent_token = (
            self.manager._active_tool_agent.set(self.agent)
            if self.manager
            else None
        )
        active_team_token = (
            self.manager._active_team.set(self.team)
            if self.manager
            else None
        )
        invocation_token = (
            self.manager._active_tool_invocation_id.set(call_id)
            if self.manager
            else None
        )
        try:
            try:
                checked_args, checked_kwargs = tool.validate_arguments(
                    list(args or []), dict(kwargs or {})
                )
            except ToolArgumentError as exc:
                return ToolResult(
                    call_id,
                    tool_name,
                    str(exc),
                    raw,
                    status=ToolResultStatus.INVALID_ARGUMENTS,
                    error_kind="argument_validation",
                )

            auditor = (
                self.manager.tool_auditors.get(tool_name)
                if self.manager
                else None
            )
            if auditor is not None:
                try:
                    if inspect.iscoroutinefunction(auditor):
                        approved, reason = await auditor(
                            *checked_args, **checked_kwargs
                        )
                    else:
                        audit_result = await asyncio.to_thread(
                            auditor, *checked_args, **checked_kwargs
                        )
                        if inspect.isawaitable(audit_result):
                            audit_result = await audit_result
                        approved, reason = audit_result
                except ATTException:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    return ToolResult(
                        call_id,
                        tool_name,
                        f"Tool audit failed: {exc}",
                        raw,
                        status=ToolResultStatus.INTERNAL_ERROR,
                        error_kind="auditor_failure",
                    )
                if approved is not True:
                    return ToolResult(
                        call_id,
                        tool_name,
                        f"Tool execution was denied by its auditor: {reason}",
                        raw,
                        status=ToolResultStatus.DENIED,
                        error_kind="auditor_denied",
                    )

            policy = (
                self.manager.config.tool_execution_retry_policy
                if self.manager
                else "never"
            )
            max_retries = (
                self.manager.config.max_tool_execution_retries
                if self.manager
                else 0
            )
            backoff = (
                self.manager.config.tool_execution_retry_backoff_factor
                if self.manager
                else 0.0
            )
            attempts = 0
            while True:
                attempts += 1
                try:
                    value = await tool.invoke_validated(
                        *checked_args, **checked_kwargs
                    )
                    return ToolResult(
                        call_id,
                        tool_name,
                        tool.serialize_result(value),
                        raw,
                        attempts=attempts,
                    )
                except ToolArgumentError as exc:
                    return ToolResult(
                        call_id,
                        tool_name,
                        str(exc),
                        raw,
                        status=ToolResultStatus.INVALID_ARGUMENTS,
                        error_kind="argument_validation",
                        attempts=attempts,
                    )
                except (ToolPermissionError, PermissionError) as exc:
                    return ToolResult(
                        call_id,
                        tool_name,
                        str(exc),
                        raw,
                        status=ToolResultStatus.DENIED,
                        error_kind="permission_denied",
                        attempts=attempts,
                    )
                except ToolBusinessError as exc:
                    return ToolResult(
                        call_id,
                        tool_name,
                        str(exc),
                        raw,
                        status=ToolResultStatus.BUSINESS_ERROR,
                        error_kind="business_error",
                        attempts=attempts,
                    )
                except RetryableToolError as exc:
                    eligible = policy == "typed_transient" or (
                        policy == "retry_safe" and tool.retry_safe
                    )
                    if eligible and attempts <= max_retries:
                        delay = float(backoff) * (2 ** (attempts - 1))
                        if delay:
                            await asyncio.sleep(delay)
                        continue
                    return ToolResult(
                        call_id,
                        tool_name,
                        str(exc),
                        raw,
                        status=ToolResultStatus.TRANSIENT_ERROR,
                        error_kind="transient_execution",
                        attempts=attempts,
                    )
                except ATTException:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    return ToolResult(
                        call_id,
                        tool_name,
                        f"{type(exc).__name__}: {exc}",
                        raw,
                        status=ToolResultStatus.INTERNAL_ERROR,
                        error_kind="tool_internal_error",
                        attempts=attempts,
                    )
        finally:
            if self.manager and active_agent_token is not None:
                self.manager._active_tool_agent.reset(active_agent_token)
            if self.manager and active_team_token is not None:
                self.manager._active_team.reset(active_team_token)
            if self.manager and invocation_token is not None:
                self.manager._active_tool_invocation_id.reset(invocation_token)
