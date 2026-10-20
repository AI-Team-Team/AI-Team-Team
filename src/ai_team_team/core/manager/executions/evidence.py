"""Shared execution evidence for coordinated foreground and independent workers."""

import asyncio

from ai_team_team.core.strategies.shared import _is_private_call
from ai_team_team.database.persistence.records import thaw
from ..activity.values import capture, identifier, scope_fields
from .dispatch import digest


class EvidenceMixin:
    async def admission_records(self, context, tool, args, kwargs, *, execution_id, call_id,
                                visibility="foreground", description="", labels=(), sources=()):
        bound = tool._signature.bind(*thaw(args), **thaw(kwargs))
        private = _is_private_call(tool.name, dict(bound.arguments))
        inputs = {"arguments": {} if private else {"args": thaw(args), "kwargs": thaw(kwargs)}, "transient": private}
        input_digest = await asyncio.to_thread(digest, inputs)
        return (
            capture(self.manager, "executions", execution_id=execution_id, agent_id=context.agent_id,
                invocation_id=context.invocation_id, **scope_fields(context.scope), tool_name=tool.name,
                effects=tool.execution_contract.effects, runtime_generation=context.generation,
                visibility=visibility, status="queued", attention="none", outcome_unconfirmed=0,
                created_at=self.clock.wall_time(), call_id=call_id,
                contract_snapshot={**tool.execution_contract.model_dump(mode="json"), "executor": tool.executor,
                                   "result_storage": tool.result_storage},
                metadata={"description": description, "labels": list(labels), "origin": "model" if context.invocation_id else "host"},
                source_references=sources),
            capture(self.manager, "execution_payloads", payload_id=f"INPUT-{execution_id}", agent_id=context.agent_id,
                execution_id=execution_id, content_kind="input", content=inputs, digest=input_digest),
        )

    async def prepare_result(self, tool, result):
        transient = tool.result_storage == "transient"
        content = {"status": result.status.value, "content": None if transient else result.content,
                   "error_kind": result.error_kind, "attempts": result.attempts, "transient": transient}
        return content, await asyncio.to_thread(digest, content)

    def result_payload(self, execution_id, owner, prepared):
        content, content_digest = prepared
        return capture(self.manager, "execution_payloads", payload_id=f"RESULT-{execution_id}",
                       agent_id=owner, execution_id=execution_id, content_kind="result", content=content, digest=content_digest)
