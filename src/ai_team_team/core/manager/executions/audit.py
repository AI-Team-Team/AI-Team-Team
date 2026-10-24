"""Restricted receipt adapter; validation, retries, bindings, and scope are shared."""

import asyncio

from ai_team_team.core.response import ToolResultStatus
from ai_team_team.core.tool_runtime import ToolExecutor

from ..activity.values import capture, identifier
from .values import ExecutionContext, ExecutorCall, Job


class AuditExecutionMixin:
    async def execute_audit_profile(self, session, name, args, kwargs, *, call_id, tools):
        profile = self.manager._activity.require_audit_profile(session.agent_id)
        tool = tools.get(name)
        allowed = {"read_audit_evidence", "share_audit_finding", "read_audit_conversation",
                   "submit_health_finding", "set_activity_intent"}
        owner = self.manager._activity.require_agent(session.agent_id)
        executor = ToolExecutor(self.manager._activity.team_for(session), owner, self.manager)
        if tool is None or name not in allowed:
            return await executor.execute(name, args, kwargs, call_id=call_id, tools={})
        if (tool.execution_contract.background_allowed or tool.executor != "callable"
                or tool.resource_resolver is None or tuple(tool.resource_resolver(session.scope, {}))):
            raise PermissionError("An audit tool must be a source-free restricted foreground operation.")
        context = ExecutionContext(session.agent_id, session.invocation_id, session.generation, session.scope)
        execution_id = identifier("AUDIT-EXECUTION")
        retry = {"policy": "never", "max_retries": 0, "backoff": 0, "retry_safe": False}
        job = Job(execution_id, context, tool, tuple(args), kwargs, call_id, (), (), retry)
        row = capture(self.manager, "audit_execution_evidence", execution_id=execution_id,
            audit_id=profile["audit_id"], scoped_agent_id=session.agent_id, tool_name=name,
            effects=list(tool.execution_contract.effects), attempt_index=1, runtime_generation=session.generation,
            status="queued", health="healthy", attention="none", sanitized_result={}, outcome_unconfirmed=0)
        await self.manager._records.commit((row,))

        async def before_attempt(index):
            self.manager._activity.check_generation(session)
            await self.manager._records.commit((capture(self.manager, "audit_execution_evidence",
                execution_id=execution_id, status="running"),))

        async def invoke(*checked_args, **checked_kwargs):
            self.manager._activity.check_generation(session)
            call = ExecutorCall(execution_id, session.agent_id, session.scope, tool,
                tuple(checked_args), checked_kwargs)
            return await self.bindings[tool.executor].execute(call, job)

        try:
            with self.context(context, execution_id), self.manager._resources.execution():
                result = await executor.execute(name, args, kwargs, call_id=call_id,
                    invocation_id=execution_id, tools={name: tool}, before_attempt=before_attempt,
                    invoke=invoke, retry_config=retry)
            await self.manager._records.commit((capture(self.manager, "audit_execution_evidence",
                execution_id=execution_id, status="failed" if result.failed else "completed",
                health="degraded" if result.failed else "healthy", outcome_unconfirmed=0,
                sanitized_result={"status": result.status.value, "error_kind": result.error_kind,
                                  "attempts": result.attempts}),))
            return result
        except BaseException:
            confirmed = self.manager._records.index.get(row.identity)
            if confirmed is not None and confirmed.values["status"] in {"completed", "failed", "cancelled"}:
                raise
            with self.manager._resources.settlement():
                await self.manager._records.commit((capture(self.manager, "audit_execution_evidence",
                    execution_id=execution_id, status="running" if job.pending_threads else "cancelled",
                    health="unknown", attention="required", outcome_unconfirmed=int(bool(job.pending_threads)),
                    sanitized_result={"status": ToolResultStatus.INTERNAL_ERROR.value}),), allow_closing=True)
            raise
