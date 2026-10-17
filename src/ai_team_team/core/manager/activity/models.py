"""Bounded provider requests with durable dispatch, claims, and factual usage."""

import asyncio
import contextvars
import inspect
import math
import random
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime

from ai_team_team.core.response import LLMResponse
from ai_team_team.core.utils import (
    _actual_usage,
    _configured_output_limit,
    _count_request_input_tokens,
    _is_retryable_llm_error,
    _output_limit_parameter,
    _usage_field,
    _invoke_sync_provider,
)
from ai_team_team.database.persistence.records import freeze, thaw

from .values import ModelUnavailable, capture, identifier


class ModelRequestService:
    def __init__(self, activity):
        self.activity = activity
        self.manager = activity.manager
        self.live = {}
        self.tasks = set()
        self.jitter = random.uniform
        self.admitted_requests = 0
        self.capacity = asyncio.Event()

    async def acquire_slot(self):
        self.capacity.set()
        while self.admitted_requests >= self.manager.config.activity.max_concurrent_model_requests:
            self.capacity.clear()
            await self.capacity.wait()
        self.admitted_requests += 1

    def release_slot(self):
        self.admitted_requests -= 1
        self.capacity.set()

    async def wait_deadline(self, deadline):
        await self.activity.clock.sleep(max(0, deadline - self.activity.clock.monotonic()))

    def retry_boundary(self, error):
        """Typed provider metadata only; never classify error message strings."""
        value = getattr(error, "retry_after", None)
        if value is None:
            headers = getattr(getattr(error, "response", None), "headers", {})
            value = (
                headers.get("Retry-After", headers.get("retry-after"))
                if hasattr(headers, "get")
                else None
            )
        if isinstance(value, bool) or value is None:
            return None
        try:
            delay = float(value)
            if math.isfinite(delay) and delay >= 0:
                return self.activity.clock.wall_time() + delay
        except (TypeError, ValueError, OverflowError):
            try:
                return max(
                    self.activity.clock.wall_time(), parsedate_to_datetime(value).timestamp()
                )
            except (TypeError, ValueError, OverflowError, AttributeError):
                pass
        return None

    @asynccontextmanager
    async def provider_slot(self, session, timeout):
        acquire = asyncio.create_task(self.acquire_slot())
        timer = asyncio.create_task(self.wait_deadline(self.activity.clock.monotonic() + timeout))
        try:
            done, _pending = await asyncio.wait(
                (acquire, timer), return_when=asyncio.FIRST_COMPLETED
            )
            if acquire not in done:
                raise TimeoutError(
                    "The model sequence budget expired waiting for provider capacity."
                )
            yield
        finally:
            acquire.cancel()
            timer.cancel()

            async def release():
                await asyncio.gather(acquire, timer, return_exceptions=True)
                if acquire.cancelled() or acquire.exception() is not None:
                    return
                live = self.live.get(session.agent_id)
                if live is not None and not live.done():
                    live.add_done_callback(lambda _done: self.release_slot())
                else:
                    self.release_slot()

            from ai_team_team.database.persistence.receipts import settle_commit

            await settle_commit(asyncio.create_task(release()))

    async def _call(self, client, kwargs):
        generate = getattr(client, "generate", client)
        if inspect.iscoroutinefunction(generate):
            return await generate(**kwargs)
        result = await _invoke_sync_provider(generate, **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def bounded_call(self, session, client, kwargs, timeout):
        deadline = self.activity.clock.monotonic() + timeout
        previous = self.live.get(session.agent_id)
        if previous is not None and not previous.done():
            raise ModelUnavailable(
                "A previous local provider request has not stopped.", recoverable=True
            )
        provider_context = contextvars.Context()
        # A trusted adapter can inspect factual scope, but receives no tool
        # actor, personal admission, or inherited governance authority.
        provider_context.run(self.manager._active_team.set, getattr(session, "provider_team", None))
        task = asyncio.create_task(
            self._call(client, kwargs),
            context=provider_context,
            name=f"att-provider-{session.agent_id}",
        )
        self.live[session.agent_id] = task
        self.tasks.add(task)

        def finished(done):
            self.tasks.discard(done)
            if self.live.get(session.agent_id) is done:
                self.live.pop(session.agent_id, None)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        timer = asyncio.create_task(self.wait_deadline(deadline), context=contextvars.Context())
        try:
            done, _ = await asyncio.wait((task, timer), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                result = task.result()
                if self.activity.clock.monotonic() < deadline:
                    return result
                error = TimeoutError("The model response arrived after its admitted deadline.")
                error.usage = getattr(result, "usage", None)
                raise error
            task.cancel()
            await asyncio.sleep(0)
            raise TimeoutError("The model request exceeded its admitted local wait budget.")
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)

    async def availability(
        self, session, alias, sequence_id, error, *, earliest=None, recoverable=False
    ):
        policy = self.manager.config.activity.llm
        live = self.live.get(session.agent_id)
        record = capture(
            self.manager,
            "model_availability",
            agent_id=session.agent_id,
            model_alias=alias,
            sequence_id=sequence_id,
            status="recoverable" if recoverable else "remediation_required",
            reason=type(error).__name__,
            request_budget=min(
                policy.sequence_timeout_seconds,
                policy.model_timeouts.get(alias, policy.request_timeout_seconds),
            ),
            sequence_budget=policy.sequence_timeout_seconds,
            earliest_admission_at=earliest,
            last_confirmed={
                "error_type": type(error).__name__,
                "local_request_pending": live is not None and not live.done(),
            },
        )
        await self.activity.commit(session, (record,))
        self.manager._emit_callback(
            "on_system_event",
            "model_unavailable",
            {
                "agent_id": session.agent_id,
                "model_alias": alias,
                "sequence_id": sequence_id,
                "error_type": type(error).__name__,
                "recoverable": recoverable,
                "earliest_admission_at": earliest,
            },
        )

    async def generate(
        self,
        session,
        *,
        client,
        prompt,
        system_instruction,
        tools=None,
        temperature=0.3,
        require_json=False,
        maintenance_segment=None,
        audit_profile=None,
    ):
        manager, activity = self.manager, self.activity
        policy = manager.config.activity.llm
        alias = manager.resolve_model_alias(client)
        sequence_id = identifier("SEQUENCE")
        start = activity.clock.monotonic()
        deadline = start + policy.sequence_timeout_seconds
        if audit_profile is not None:
            deadline = min(
                deadline, start + max(0, audit_profile["deadline"] - activity.clock.wall_time())
            )
        earliest = None
        failure = None
        immutable_prompt = freeze(prompt)
        prompt_copy = await asyncio.to_thread(thaw, immutable_prompt)
        input_tokens = await asyncio.to_thread(
            _count_request_input_tokens, manager, alias, prompt_copy, system_instruction, tools
        )
        output_budget = _configured_output_limit(manager, alias)
        retries = policy.max_retries if maintenance_segment is None else 0
        for attempt in range(1, retries + 2):
            if attempt > 1 and maintenance_segment is None and audit_profile is None:
                await activity.prepare_frame(session)
                prompt_copy = await asyncio.to_thread(
                    thaw, freeze(activity.require_agent(session.agent_id).messages)
                )
                input_tokens = await asyncio.to_thread(
                    _count_request_input_tokens,
                    manager,
                    alias,
                    prompt_copy,
                    system_instruction,
                    tools,
                )
            remaining = deadline - activity.clock.monotonic()
            if remaining <= 0:
                break
            timeout = min(
                policy.model_timeouts.get(alias, policy.request_timeout_seconds), remaining
            )
            request_id = identifier("REQUEST")
            if audit_profile is not None:
                request = capture(
                    manager,
                    "audit_model_requests",
                    request_id=request_id,
                    audit_id=audit_profile["audit_id"],
                    scoped_agent_id=session.agent_id,
                    invocation_id=session.invocation_id,
                    frame_id=identifier("AUDIT-FRAME"),
                    input_version=0,
                    model_alias=alias,
                    attempt_index=attempt,
                    dispatch_state="unsent",
                    outcome="pending",
                    created_at=activity.clock.wall_time(),
                    request_budget=timeout,
                    sequence_budget=remaining,
                )
            elif maintenance_segment is None:
                request = capture(
                    manager,
                    "model_requests",
                    model_request_id=request_id,
                    frame_id=session.frame_id,
                    agent_id=session.agent_id,
                    model_alias=alias,
                    attempt_index=attempt,
                    input_version=session.context_version,
                    dispatch_state="unsent",
                    outcome="pending",
                    created_at=activity.clock.wall_time(),
                    request_budget=timeout,
                    sequence_budget=remaining,
                )
            else:
                from ai_team_team.core.memory.sanitization import content_digest

                request = capture(
                    manager,
                    "memory_index_requests",
                    request_id=request_id,
                    segment_id=maintenance_segment.segment_id,
                    beneficiary_agent_id=maintenance_segment.agent_id,
                    source_version=1,
                    model_alias=alias,
                    attempt_index=maintenance_segment.attempts + 1,
                    input_digest=content_digest(str(prompt)),
                    dispatch_state="unsent",
                    outcome="pending",
                    created_at=activity.clock.wall_time(),
                )
            claim_id = None
            sent = False
            response = None
            try:
                claim_id = await manager.token_budget.reserve_request(
                    request,
                    input_tokens,
                    output_budget,
                    related_records=activity.claim_records(session, request_id, "reserved")
                    if maintenance_segment is None and audit_profile is None
                    else (),
                )
                parameter = _output_limit_parameter(client)
                if alias in manager.config.model_token_limits and parameter is None:
                    raise ValueError("A quota-limited client must accept an output-token limit.")
                kwargs = {
                    "prompt": prompt_copy,
                    "system_instruction": system_instruction,
                    "temperature": temperature,
                    "require_json": require_json,
                }
                if tools:
                    kwargs["tools"] = tools
                if parameter:
                    kwargs[parameter] = output_budget
                async with self.provider_slot(
                    session, max(0, deadline - activity.clock.monotonic())
                ):
                    self.check_request(session, maintenance_segment, audit_profile)
                    remaining_now = deadline - activity.clock.monotonic()
                    if remaining_now <= 0:
                        raise TimeoutError("The sequence budget expired before provider dispatch.")
                    timeout = min(timeout, remaining_now)
                    dispatched = capture(
                        manager,
                        request.table_name,
                        **{
                            **{
                                key: value
                                for key, value in request.values.items()
                                if key != "state_version"
                            },
                            "dispatch_state": "sent",
                            "dispatched_at": max(
                                activity.clock.wall_time(), request.values["created_at"]
                            ),
                        },
                    )
                    await activity.commit(
                        session,
                        (
                            dispatched,
                            *(
                                activity.claim_records(session, request_id, "dispatched")
                                if maintenance_segment is None and audit_profile is None
                                else ()
                            ),
                        ),
                    )
                    self.check_request(session, maintenance_segment, audit_profile)
                    remaining_now = deadline - activity.clock.monotonic()
                    if remaining_now <= 0:
                        error = TimeoutError(
                            "The sequence budget expired before provider dispatch."
                        )
                        error.request_sent = False
                        raise error
                    timeout = min(timeout, remaining_now)
                    session.availability = "waiting_model"
                    sent = True
                    response = await self.bounded_call(session, client, kwargs, timeout)
                    self.check_request(session, maintenance_segment, audit_profile)
                if isinstance(response, str):
                    response = LLMResponse(text=response)
                if not isinstance(response, LLMResponse):
                    raise TypeError("A model client must return text or LLMResponse.")
                call_ids = [call.call_id for call in response.tool_calls]
                if any(
                    not isinstance(identity, str) or not identity.strip() for identity in call_ids
                ) or len(set(call_ids)) != len(call_ids):
                    error = ValueError(
                        "Native tool-call identities must be nonblank and unique within a batch."
                    )
                    error.usage = response.usage
                    raise error
                output_text = response.text or ""
                if response.tool_calls:
                    import json

                    output_text += json.dumps(
                        [call.to_dict() for call in response.tool_calls], ensure_ascii=False
                    )
                actual = _actual_usage(
                    response, input_tokens, manager.count_tokens(output_text, alias)
                )
                await manager.token_budget.settle_claim(
                    claim_id,
                    settlement="known_usage",
                    actual_usage=actual,
                    outcome="completed",
                    allow_closing=True,
                )
                session.last_request_id = request_id
                session.availability = "ready"
                return response
            except BaseException as error:
                # Cancellation may have arrived after a claim committed but before
                # reserve_request returned its identity to this observer.
                if claim_id is None:
                    claim_id = next(
                        (
                            row.values["claim_id"]
                            for row in manager._records.snapshot()
                            if row.table_name == "model_token_claims"
                            and request_id
                            in (
                                row.values["model_request_id"],
                                row.values["index_request_id"],
                                row.values["audit_request_id"],
                            )
                        ),
                        None,
                    )
                if claim_id is not None:
                    claim = manager._records.index[("model_token_claims", (claim_id,))]
                    if claim.values["settlement"] == "reserved":
                        confirmed_unsent = not sent or getattr(error, "request_sent", None) is False
                        usage = getattr(error, "usage", None)
                        usage_source = error
                        if usage is None and response is not None:
                            usage = getattr(response, "usage", None)
                            usage_source = response
                        known = (
                            usage is not None
                            and _usage_field(
                                usage,
                                "total_tokens",
                                "total_token_count",
                                "prompt_tokens",
                                "input_tokens",
                            )
                            is not None
                        )
                        settlement = (
                            "confirmed_unsent"
                            if confirmed_unsent
                            else "known_usage"
                            if known
                            else "unknown_sent"
                        )
                        await manager.token_budget.settle_claim(
                            claim_id,
                            settlement=settlement,
                            actual_usage=_actual_usage(usage_source, input_tokens, 0)
                            if known and not confirmed_unsent
                            else None,
                            outcome="cancelled"
                            if isinstance(error, asyncio.CancelledError)
                            else "failed",
                            allow_closing=True,
                        )
                        if (
                            sent
                            and not confirmed_unsent
                            and maintenance_segment is None
                            and audit_profile is None
                        ):
                            await activity.commit(
                                session, activity.claim_records(session, request_id, "uncertain")
                            )
                if isinstance(error, asyncio.CancelledError):
                    raise
                from ai_team_team.core.exceptions import (
                    StatePersistenceError,
                    StateRestoreError,
                    DatabaseOwnershipError,
                    AgentInvocationDependencyError,
                )

                if isinstance(
                    error,
                    (
                        StatePersistenceError,
                        StateRestoreError,
                        DatabaseOwnershipError,
                        AgentInvocationDependencyError,
                    ),
                ):
                    raise
                failure = error
                recoverable = (
                    _is_retryable_llm_error(error)
                    or isinstance(error, ModelUnavailable)
                    and error.recoverable
                )
                earliest = self.retry_boundary(error)
                if (
                    earliest is not None
                    and maintenance_segment is None
                    and ("model_requests", (request_id,)) in manager._records.index
                ):
                    await activity.commit(
                        session,
                        (
                            capture(
                                manager,
                                "model_requests",
                                model_request_id=request_id,
                                earliest_retry_at=earliest,
                            ),
                        ),
                    )
                local_pending = (
                    session.agent_id in self.live and not self.live[session.agent_id].done()
                )
                if not recoverable or local_pending or attempt > retries:
                    break
                delay = self.jitter(
                    0,
                    min(
                        policy.backoff_cap_seconds, policy.backoff_base_seconds * 2 ** (attempt - 1)
                    ),
                )
                if earliest is not None:
                    delay = max(delay, earliest - activity.clock.wall_time())
                if delay >= deadline - activity.clock.monotonic():
                    break
                if delay:
                    await activity.clock.sleep(delay)
        failure = failure or TimeoutError("The model retry sequence exhausted its time budget.")
        recoverable = (
            _is_retryable_llm_error(failure)
            or isinstance(failure, ModelUnavailable)
            and failure.recoverable
        )
        boundary = (
            max(activity.clock.wall_time() + policy.recovery_delay_seconds, earliest or 0)
            if recoverable
            else None
        )
        if maintenance_segment is None and audit_profile is None:
            await self.availability(
                session, alias, sequence_id, failure, earliest=boundary, recoverable=recoverable
            )
        raise ModelUnavailable(
            f"Model {alias!r} is unavailable ({type(failure).__name__}).",
            recoverable=recoverable,
            earliest=boundary,
        ) from failure

    def check_request(self, session, segment, audit_profile=None):
        if audit_profile is not None:
            team = self.manager.teams.get(audit_profile["temporary_team_id"])
            if (
                self.activity.closing
                or self.manager._closing
                or session.generation != self.activity.generation
                or team is None
                or team.team_kind != "supervisory"
                or not any(agent.agent_id == session.agent_id for agent in team.members)
            ):
                raise asyncio.CancelledError("The scoped audit request is no longer eligible.")
            if audit_profile["deadline"] <= self.activity.clock.wall_time():
                raise TimeoutError("The audit request deadline has elapsed.")
            return
        if segment is None:
            self.activity.check_generation(session)
            return
        if (
            self.activity.closing
            or self.manager._closing
            or session.generation != self.activity.generation
            or self.manager._memory.segments.get(segment.segment_id) is not segment
            or not self.manager.config.episodic_memory.enabled
        ):
            raise asyncio.CancelledError("The indexing maintenance request is no longer eligible.")
        self.activity.require_agent(segment.agent_id)

    async def index(self, agent, segment, prompt, system_instruction):
        from .values import Session

        session = Session(
            f"index:{segment.segment_id}", f"index:{segment.segment_id}", self.activity.generation
        )
        response = await self.generate(
            session,
            client=agent.llm_client,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.1,
            require_json=True,
            maintenance_segment=segment,
        )
        return response.text or ""

    async def audit(self, audit_id, agent, prompt, system_instruction, **kwargs):
        from .values import Session

        row = self.manager._records.index.get(("audit_runs", (audit_id,)))
        participant = self.manager._records.index.get(
            ("audit_participants", (audit_id, agent.agent_id))
        )
        if row is None or participant is None or row.values["status"] != "running":
            raise PermissionError(
                "An audit request requires its retained run and exact scoped participant."
            )
        session = Session(agent.agent_id, audit_id, self.activity.generation)
        session.invocation_id = identifier("AUDIT-INVOCATION")
        session.provider_team = self.manager.teams.get(row.values["temporary_team_id"])
        return await self.generate(
            session,
            client=agent.llm_client,
            prompt=prompt,
            system_instruction=system_instruction,
            audit_profile=row.values,
            **kwargs,
        )

    def close(self):
        for task in tuple(self.tasks):
            task.cancel()
