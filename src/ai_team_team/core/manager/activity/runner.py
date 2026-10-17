"""Bounded personal invocations; neither backend decides business completion."""

import asyncio

from ai_team_team.core.exceptions import ToolArgumentError
from ai_team_team.core.response import ToolResult, ToolResultStatus
from ai_team_team.core.strategies.native import _close_interrupted_tool_batch
from ai_team_team.core.strategies.shared import (
    _extract_final_answer,
    _privacy_safe_agent_output,
    _redact_private_log,
    _redact_private_tool_calls,
    _scrub_private_window_messages,
    _PRIVATE_TOOL_NAMES,
)
from ai_team_team.core.text_action import parse_text_action, parse_tool_arguments

from .tools import ForegroundToolMixin
from .values import ModelUnavailable, capture, identifier, scope_fields


class RunnerMixin(ForegroundToolMixin):
    async def run(self, session):
        manager = self.manager
        agent = manager._agents_by_id.get(session.agent_id)
        tokens = []
        try:
            self.check_generation(session)
            async with manager.agent_invocation(agent):
                # All window changes, including cancellation cleanup and failed
                # checkpoints, stay inside the same person's invocation guard.
                try:
                    self.check_generation(session)
                    session.invocation_id = identifier("INVOCATION")
                    tokens = [
                        (self.current, self.current.set(session)),
                        (manager._active_team, manager._active_team.set(self.team_for(session))),
                        (manager._active_discussion_id, manager._active_discussion_id.set(None)),
                        (
                            manager._active_agent_turn_id,
                            manager._active_agent_turn_id.set(session.invocation_id),
                        ),
                        (manager._active_round_number, manager._active_round_number.set(None)),
                    ]
                    await self.run_invocation(session, agent)
                except BaseException as error:
                    _close_interrupted_tool_batch(self.team_for(session), agent, manager)
                    await self.interrupt(session, error)
                    if not isinstance(error, ModelUnavailable):
                        raise
                finally:
                    _scrub_private_window_messages(agent)
        except BaseException as error:
            if session.active:
                await self.interrupt(session, error, window=False)
            if not isinstance(error, asyncio.CancelledError):
                manager._emit_callback(
                    "on_system_event",
                    "activity_failed",
                    {
                        "agent_id": session.agent_id,
                        "admission_id": session.admission_id,
                        "error_type": type(error).__name__,
                    },
                )
            raise
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)
            session.running = False
            if session.failure is not None:
                self.response_observed(session)
                for future, _intent in tuple(self.waiters.get(session.admission_id, ())):
                    if not future.done():
                        future.set_exception(session.failure)
            if session.active and not self.closing:
                self.enqueue(session)

    async def interrupt(self, session, error, *, window=True):
        admission = self.manager._records.index.get(
            ("activity_admissions", (session.admission_id,))
        )
        if admission is not None and admission.values["disposition"] == "completed":
            # An idle/sleep transaction can commit before cancellation reaches
            # its caller. Its receipt cannot be rewritten as an interruption.
            self.finish_boundary(session)
            return
        session.failure = error
        session.active = False
        session.availability = "closing" if self.closing else "unavailable"
        records = (
            capture(
                self.manager,
                "activity_admissions",
                admission_id=session.admission_id,
                disposition="interrupted",
            ),
        )
        async with self.lock:
            if window:
                await self.checkpoint(session, end_invocation=True, interrupted=True, extra=records)
            else:
                await self.commit(session, (*records, self.marker(session)), allow_closing=True)
        if (
            isinstance(error, ModelUnavailable)
            and error.recoverable
            and error.earliest is not None
            and not self.closing
        ):
            self.arm_timer(session, max(0, error.earliest - self.clock.wall_time()), recovery=True)

    async def run_invocation(self, session, agent):
        manager = self.manager
        async with self.lock:
            invocation = capture(
                manager,
                "activity_invocations",
                invocation_id=session.invocation_id,
                admission_id=session.admission_id,
                agent_id=session.agent_id,
                runtime_generation=session.generation,
                **scope_fields(session.scope),
                context_version=session.context_version,
                started_at=self.clock.wall_time(),
                interrupted=0,
            )
            await self.commit(session, (invocation, self.marker(session)))
        manager._memory.record_event(
            "activity_invocation_started",
            agent=agent,
            team=self.team_for(session),
            invocation_id=session.invocation_id,
            inherit_context=False,
        )
        _close_interrupted_tool_batch(self.team_for(session), agent, manager)
        if not agent.messages:
            self.append(
                session,
                {
                    "role": "user",
                    "content": "Continue your own admitted activity. You may deliberately choose idle or finite sleep.",
                },
            )
        native = manager.config.tool_calling_mode == "native" or (
            manager.config.tool_calling_mode == "auto"
            and manager.probe_native_tool_capability(
                agent.llm_client, agent=agent, team=self.team_for(session)
            )
        )
        batches = 0
        for _request_index in range(manager.config.activity.model_requests_per_invocation):
            self.check_generation(session)
            tools = manager.get_available_tools(self.team_for(session), agent)
            tools.update(self.control_tools(session))
            await self.prepare_frame(session)
            response = await self.models.generate(
                session,
                client=agent.llm_client,
                prompt=agent.messages,
                system_instruction=self.instructions(session, tools, native),
                tools=list(tools.values()) if native else None,
            )
            self.check_generation(session)
            text = response.text or ""
            session.answer = ""
            if native:
                await self.native_response(session, response, tools)
                had_batch = bool(response.tool_calls)
            else:
                had_batch = await self.text_response(session, text, tools)
            async with self.lock:
                await self.checkpoint(session)
            if had_batch:
                batches += 1
            if session.pending_intent is not None or session.pending_scope is not None:
                break
            if batches >= manager.config.activity.tool_batches_per_invocation:
                break
        await self.end_invocation(session)

    async def native_response(self, session, response, tools):
        agent = self.require_agent(session.agent_id)
        calls = response.tool_calls
        if any(
            not isinstance(call.call_id, str) or not call.call_id.strip() for call in calls
        ) or len({call.call_id for call in calls}) != len(calls):
            raise ValueError(
                "Native tool-call identities must be nonblank and unique within a batch."
            )
        message = {
            "role": "assistant",
            "content": _privacy_safe_agent_output(agent, response.text or ""),
        }
        if calls:
            if any(call.name in _PRIVATE_TOOL_NAMES for call in calls):
                message["content"] = "[private tool payload redacted]"
            message["tool_calls"] = _redact_private_tool_calls([call.to_dict() for call in calls])
        self.append(session, message, capture_content=not calls)
        async with self.lock:
            await self.checkpoint(
                session, extra=self.claim_records(session, session.last_request_id, "presented")
            )
        if not calls:
            session.answer = response.text or ""
            self.response_observed(session, answer_ready=True)
            return
        duplicated = {
            name
            for name in ("set_activity_intent", "set_operation_scope")
            if sum(call.name == name for call in calls) > 1
        }
        executions = []
        for call in calls:
            if (
                duplicated
                and call.name in {"set_activity_intent", "set_operation_scope"}
                or not isinstance(call.arguments, dict)
            ):
                executions.append(
                    asyncio.sleep(
                        0,
                        result=ToolResult(
                            call.call_id,
                            call.name,
                            "Duplicate controls or non-object arguments are invalid before control effects execute.",
                            status=ToolResultStatus.INVALID_ARGUMENTS,
                            error_kind="batch_control_conflict",
                        ),
                    )
                )
            else:
                executions.append(
                    self.execute_tool(
                        session, call.name, [], call.arguments, call_id=call.call_id, tools=tools
                    )
                )
        session.availability = "waiting_tool"
        results = await self.execute_batch(executions)
        self.check_generation(session)
        for result in results:
            self.append_observation(session, result, tools, True)
        session.availability = "ready"

    async def text_response(self, session, text, tools):
        agent = self.require_agent(session.agent_id)
        import re

        has_action = bool(
            re.search(r"(?im)^\s*Action\s*:", text)
            or re.search(r"<action\s+name=", text, re.IGNORECASE)
        )
        self.append(
            session,
            {
                "role": "assistant",
                "content": _redact_private_log(_privacy_safe_agent_output(agent, text))
                if has_action
                else _privacy_safe_agent_output(agent, text),
            },
            capture_content=not has_action,
        )
        async with self.lock:
            await self.checkpoint(
                session, extra=self.claim_records(session, session.last_request_id, "presented")
            )
        if not has_action:
            session.answer = _extract_final_answer(text) or text
            self.response_observed(session, answer_ready=True)
            return False
        try:
            action = parse_text_action(text)
            args, kwargs = parse_tool_arguments(action.arguments)
            session.availability = "waiting_tool"
            result = (
                await self.execute_batch(
                    [
                        self.execute_tool(
                            session,
                            action.name,
                            args,
                            kwargs,
                            call_id=identifier("CALL"),
                            tools=tools,
                        )
                    ]
                )
            )[0]
        except ToolArgumentError as error:
            result = ToolResult(
                identifier("CALL"),
                "<action>",
                str(error),
                status=ToolResultStatus.INVALID_ARGUMENTS,
                error_kind="action_parse",
            )
        self.check_generation(session)
        self.append_observation(session, result, tools, False)
        session.availability = "ready"
        return True

    def response_observed(self, session, *, answer_ready=False, stopping=False):
        event = getattr(session, "response_event", None)
        if event is not None:
            event.set()
        for mail_id, future in tuple(getattr(session, "interaction_waiters", ())):
            if future.done():
                continue
            notice_id = f"NOTICE-{mail_id}"
            presented = any(
                row.table_name == "notification_claims"
                and row.values["notification_id"] == notice_id
                and row.values["status"] == "presented"
                for row in self.manager._records.snapshot()
            )
            if session.failure is not None:
                future.set_exception(session.failure)
            elif presented and (answer_ready or stopping):
                future.set_result((session.answer, getattr(session.scope, "team_id", None)))

    async def end_invocation(self, session):
        async with self.lock:
            invocation_id = session.invocation_id
            previous = (
                session.intent,
                session.active,
                session.sleep_id,
                session.sleep_deadline,
            )
            try:
                records = []
                if session.pending_scope is not None:
                    self.validate_scope(session.agent_id, session.pending_scope)
                intent = session.pending_intent
                if intent is not None:
                    session.intent = intent.kind
                    session.active = False
                    records.append(
                        capture(
                            self.manager,
                            "activity_admissions",
                            admission_id=session.admission_id,
                            disposition="completed",
                        )
                    )
                    if intent.kind == "sleep":
                        records.extend(self.sleep_records(session, intent))
                self.manager._memory.record_event(
                    "activity_invocation_finished",
                    agent=self.require_agent(session.agent_id),
                    team=self.team_for(session),
                    invocation_id=session.invocation_id,
                    inherit_context=False,
                    payload={"intent": session.intent},
                )
                _scrub_private_window_messages(self.require_agent(session.agent_id))
                session.pending_segment_id = (
                    await self.manager._memory.finalize_activity_invocation(
                        self.require_agent(session.agent_id),
                        self.team_for(session),
                        session.invocation_id,
                    )
                )
                await self.checkpoint(session, end_invocation=True, extra=records)
            except BaseException:
                if session.invocation_id == invocation_id:
                    # No boundary receipt was published. Withdraw only the
                    # staged controls, not the person's factual observations.
                    (
                        session.intent,
                        session.active,
                        session.sleep_id,
                        session.sleep_deadline,
                    ) = previous
                    session.pending_intent = None
                    session.pending_scope = None
                raise
            self.finish_boundary(session)

    def finish_boundary(self, session):
        segment_id = getattr(session, "pending_segment_id", None)
        if segment_id is not None and not self.closing:
            self.manager._memory._schedule_segment(segment_id)
        session.pending_segment_id = None
        if session.pending_scope is not None:
            session.scope = session.pending_scope
        session.pending_intent = None
        session.pending_scope = None
        if not self.closing:
            if session.intent == "sleep":
                self.arm_timer(session, max(0, session.sleep_deadline - self.clock.monotonic()))
            elif session.intent == "idle" and self.pending_notices(session.agent_id):
                self.schedule_activation(session.agent_id, notification_only=True)
        self.response_observed(session, stopping=session.intent in {"idle", "sleep"})
