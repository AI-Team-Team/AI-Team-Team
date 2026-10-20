import asyncio
import inspect
from contextlib import nullcontext
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

    @staticmethod
    def failure_result(error, *, call_id, tool_name, raw=None, attempts=1):
        """Classify both immediate and late outcomes without replaying a call."""
        if isinstance(error, (ATTException, asyncio.CancelledError)) or not isinstance(error, Exception):
            raise error
        if isinstance(error, ToolArgumentError):
            status, kind = ToolResultStatus.INVALID_ARGUMENTS, error.error_kind or "argument_validation"
        elif isinstance(error, (ToolPermissionError, PermissionError)):
            status, kind = ToolResultStatus.DENIED, getattr(error, "error_kind", None) or "permission_denied"
        elif isinstance(error, FileNotFoundError):
            status, kind = ToolResultStatus.BUSINESS_ERROR, "not_found"
        elif isinstance(error, ToolBusinessError):
            status, kind = ToolResultStatus.BUSINESS_ERROR, error.error_kind or "business_error"
        elif isinstance(error, RetryableToolError):
            status, kind = ToolResultStatus.TRANSIENT_ERROR, "transient_execution"
        else:
            status, kind = ToolResultStatus.INTERNAL_ERROR, "tool_internal_error"
        content = "The requested file does not exist." if kind == "not_found" else (
            f"{type(error).__name__}: {error}" if status == ToolResultStatus.INTERNAL_ERROR else str(error))
        return ToolResult(call_id, tool_name, content, raw, status=status, error_kind=kind, attempts=attempts)

    async def execute(
        self,
        tool_name: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        *,
        call_id: str = "",
        invocation_id: Optional[str] = None,
        raw: Any = None,
        tools: Optional[Mapping[str, Any]] = None,
        before_attempt: Any = None,
        invoke: Any = None,
        retry_config: Any = None,
        retry_sleep: Any = None,
    ) -> ToolResult:
        registry = tools if tools is not None else getattr(self.team, "tools", {})
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
            self.manager._active_tool_agent.set(self.agent) if self.manager else None
        )
        active_team_token = self.manager._active_team.set(self.team) if self.manager else None
        invocation_token = (
            self.manager._active_tool_invocation_id.set(
                invocation_id if invocation_id is not None else call_id
            )
            if self.manager
            else None
        )
        authority = self.manager._resources.execution() if self.manager else nullcontext()
        try:
            with authority:
                return await self._execute_authorized(
                    tool,
                    tool_name,
                    args,
                    kwargs,
                    call_id=call_id,
                    raw=raw,
                    before_attempt=before_attempt,
                    invoke=invoke,
                    retry_config=retry_config,
                    retry_sleep=retry_sleep,
                )
        finally:
            if self.manager and active_agent_token is not None:
                self.manager._active_tool_agent.reset(active_agent_token)
            if self.manager and active_team_token is not None:
                self.manager._active_team.reset(active_team_token)
            if self.manager and invocation_token is not None:
                self.manager._active_tool_invocation_id.reset(invocation_token)

    async def _execute_authorized(
        self, tool, tool_name, args, kwargs, *, call_id, raw, before_attempt,
        invoke=None, retry_config=None, retry_sleep=None,
    ) -> ToolResult:
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
                error_kind=exc.error_kind or "argument_validation",
            )

        auditor = self.manager.tool_auditors.get(tool_name) if self.manager else None
        if auditor is not None:
            try:
                if inspect.iscoroutinefunction(auditor):
                    approved, reason = await auditor(*checked_args, **checked_kwargs)
                else:
                    audit_result = await asyncio.to_thread(auditor, *checked_args, **checked_kwargs)
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

        policy = self.manager.config.tool_execution_retry_policy if self.manager else "never"
        max_retries = self.manager.config.max_tool_execution_retries if self.manager else 0
        backoff = self.manager.config.tool_execution_retry_backoff_factor if self.manager else 0.0
        retry_safe = tool.retry_safe
        if retry_config is not None:
            policy, max_retries, backoff = (retry_config[key] for key in ("policy", "max_retries", "backoff"))
            retry_safe = retry_config["retry_safe"]
        attempts = 0
        while True:
            attempts += 1
            # Trusted runtime evidence is accepted before each actual
            # execution, never before validation or the tool auditor.
            try:
                if before_attempt is not None:
                    await before_attempt(attempts)
                if self.manager:
                    self.manager._resources.check_authority()
                value = await (invoke(*checked_args, **checked_kwargs) if invoke is not None
                               else tool.invoke_validated(*checked_args, **checked_kwargs))
                return ToolResult(
                    call_id,
                    tool_name,
                    tool.serialize_result(value),
                    raw,
                    attempts=attempts,
                )
            except RetryableToolError as exc:
                eligible = policy == "typed_transient" or (
                    policy == "retry_safe" and retry_safe
                )
                if eligible and attempts <= max_retries:
                    delay = float(backoff) * (2 ** (attempts - 1))
                    if delay:
                        await (retry_sleep or asyncio.sleep)(delay)
                    continue
                return self.failure_result(exc, call_id=call_id, tool_name=tool_name, raw=raw, attempts=attempts)
            except BaseException as exc:
                return self.failure_result(exc, call_id=call_id, tool_name=tool_name, raw=raw, attempts=attempts)
