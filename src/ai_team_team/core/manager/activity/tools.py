"""Foreground evidence and shared tool classification without background replay."""

import asyncio

from ai_team_team.core.response import ToolResult, ToolResultStatus
from ai_team_team.core.tool_runtime import ToolExecutor

from .values import capture, identifier, scope_fields


class ForegroundToolMixin:
    async def execute_tool(self, session, name, args, kwargs, *, call_id, tools):
        manager = self.manager
        tool = tools.get(name)
        executor = ToolExecutor(
            self.team_for(session), self.require_agent(session.agent_id), manager
        )
        if tool is None:
            return await executor.execute(name, args, kwargs, call_id=call_id, tools=tools)
        try:
            tool.validate_arguments(args, kwargs)
        except Exception as error:
            from ai_team_team.core.exceptions import ToolArgumentError

            if not isinstance(error, ToolArgumentError):
                raise
            return ToolResult(
                call_id,
                name,
                str(error),
                status=ToolResultStatus.INVALID_ARGUMENTS,
                error_kind="argument_validation",
            )
        if (
            tool.execution_contract.required_scope == "agent_team"
            and session.scope.kind != "agent_team"
        ):
            return ToolResult(
                call_id,
                name,
                "This operation requires the captured AgentTeam scope.",
                status=ToolResultStatus.DENIED,
            )
        cooling = manager._records.index.get(("tool_cooldowns", (session.agent_id, name)))
        if cooling is not None:
            values = cooling.values
            remaining = self.cooldown_remaining(cooling)
            if remaining > 0:
                return ToolResult(
                    call_id,
                    name,
                    f"Tool cooling; available in {remaining:.3f} seconds.",
                    status=ToolResultStatus.BUSINESS_ERROR,
                    error_kind="tool_cooldown",
                )
        execution_id = identifier("EXECUTION")
        admitted = capture(
            manager,
            "executions",
            execution_id=execution_id,
            agent_id=session.agent_id,
            invocation_id=session.invocation_id,
            **scope_fields(session.scope),
            tool_name=name,
            effects=tool.execution_contract.effects,
            runtime_generation=session.generation,
            visibility="foreground",
            status="queued",
            attention="none",
            outcome_unconfirmed=0,
            created_at=self.clock.wall_time(),
        )
        async with self.lock:
            await self.commit(session, (admitted,))

        async def before_attempt(index):
            self.check_generation(session)
            attempt = capture(
                manager,
                "execution_attempts",
                attempt_id=identifier("ATTEMPT"),
                execution_id=execution_id,
                attempt_index=index,
                retry_contract={
                    "policy": manager.config.tool_execution_retry_policy,
                    "max_retries": manager.config.max_tool_execution_retries,
                    "retry_safe": tool.retry_safe,
                },
                started_at=self.clock.wall_time(),
                dispatched=1,
            )
            async with self.lock:
                await self.commit(
                    session,
                    (
                        capture(manager, "executions", execution_id=execution_id, status="running"),
                        attempt,
                    ),
                )
            self.check_generation(session)

        try:
            result = await executor.execute(
                name,
                args=args,
                kwargs=kwargs,
                call_id=call_id,
                invocation_id=f"{session.invocation_id}:{call_id}",
                tools=tools,
                before_attempt=before_attempt,
            )
            self.check_generation(session)
        except BaseException:
            async with self.lock:
                await self.commit(
                    session,
                    (
                        capture(
                            manager,
                            "executions",
                            execution_id=execution_id,
                            status="running",
                            outcome_unconfirmed=1,
                            attention="required",
                        ),
                    ),
                )
            raise
        async with self.lock:
            # Native siblings may finish the same tool concurrently. Capture
            # the shared cooldown version only while owning its commit lock.
            extra = [
                capture(
                    manager,
                    "executions",
                    execution_id=execution_id,
                    status="failed" if result.failed else "completed",
                    outcome_unconfirmed=0,
                    attention="required" if result.failed else "none",
                )
            ]
            cooldown = None
            if (
                result.status in {ToolResultStatus.TRANSIENT_ERROR, ToolResultStatus.INTERNAL_ERROR}
                and result.error_kind != "auditor_failure"
            ):
                seconds = manager.config.activity.tool_cooldown_seconds
                include = manager.config.activity.cooldown_downtime == "include"
                now = self.clock.wall_time()
                deadline = self.clock.monotonic() + seconds
                cooldown = capture(
                    manager,
                    "tool_cooldowns",
                    agent_id=session.agent_id,
                    tool_name=name,
                    fault_id=execution_id,
                    accounting_mode="wall_time" if include else "remaining",
                    remaining_seconds=None if include else seconds,
                    deadline=now + seconds if include else None,
                    sampled_at=now,
                )
                extra.append(cooldown)
            try:
                await self.commit(session, extra)
            finally:
                if cooldown is not None:
                    committed = manager._records.index.get(cooldown.identity)
                    if (
                        committed is not None
                        and committed.version == cooldown.version
                        and committed.values["fault_id"] == execution_id
                    ):
                        # Receipt settlement survives caller cancellation, but
                        # an uncommitted fault must not change the live timer.
                        key = session.agent_id, name
                        if include:
                            self.cooldown_deadlines.pop(key, None)
                        else:
                            self.cooldown_deadlines[key] = deadline
        return result

    async def execute_batch(self, executions):
        with self.manager._resources.execution() as authority:
            return await self._execute_batch(executions, authority)

    async def _execute_batch(self, executions, authority):
        tasks = [asyncio.create_task(execution) for execution in executions]
        try:
            pending = set(tasks)
            while pending:
                # FIRST_EXCEPTION does not wake for a cancelled child. A
                # cancelled tool must fence every sibling immediately, even
                # when another tool is still awaiting an external service.
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        raise task.exception()
                if any(task.cancelled() for task in done):
                    raise asyncio.CancelledError()
            return [task.result() for task in tasks]
        except BaseException:
            self.manager._resources.revoke(authority)
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Local transactions settle themselves before raising cancellation;
            # arbitrary external waits are fenced, not awaited indefinitely.
            for task in tasks:
                self.tool_tasks.add(task)
                task.add_done_callback(self.tool_finished)
            await asyncio.sleep(0)
            raise

    def tool_finished(self, task):
        self.tool_tasks.discard(task)
        if not task.cancelled():
            task.exception()
