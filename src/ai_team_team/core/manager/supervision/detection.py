"""Typed observations and restart-safe rolling consecutive streaks."""

import asyncio
import contextvars
import hashlib

from ai_team_team.core.health import HealthSubject
from ai_team_team.core.response import ToolResultStatus
from ai_team_team.database.persistence.records import thaw

from ..activity.values import capture


class HealthDetectionMixin:
    async def observe(self, agent_id, detector, *, source_id, valid, tool_name=None, error_kind=None):
        if self.is_supervisory_agent(agent_id) or self.manager._closing:
            return None
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None or agent.lifecycle_state != "active":
            return None
        if type(valid) is not bool or detector not in {"model_protocol", "tool_arguments", "semantic"}:
            raise ValueError("Health observations require a typed detector outcome.")
        if detector == "semantic" and not self.manager.config.health.semantic_detection_enabled:
            return None
        if detector == "tool_arguments" and not tool_name:
            raise ValueError("Tool-argument evidence requires its exact tool identity.")
        observation_id = "HEALTH-" + hashlib.sha256(f"{agent_id}:{detector}:{tool_name}:{source_id}".encode()).hexdigest()
        evidence = None
        async with self.detection_lock:
            if ("health_observations", (observation_id,)) in self.manager._records.index:
                return None
            now = self.manager._activity.clock.wall_time()
            previous = self.manager._records.index.get(("health_detector_states", (agent_id, detector, tool_name or "-")))
            config = self.manager.config.health
            samples, observations = [], []
            if previous is not None and (detector != "tool_arguments" or previous.values["error_kind"] == error_kind):
                for moment, identity in zip(previous.values["samples"], previous.values["observation_ids"]):
                    if now - config.observation_window_seconds <= moment <= now:
                        samples.append(moment)
                        observations.append(identity)
            if valid:
                samples, observations = [], []
                error_kind = None
            else:
                samples.append(now)
                observations.append(observation_id)
            threshold = config.protocol_failure_threshold if detector == "model_protocol" else config.tool_argument_failure_threshold
            samples, observations = samples[-threshold:], observations[-threshold:]
            row = capture(self.manager, "health_observations", observation_id=observation_id, agent_id=agent_id,
                detector=detector, tool_name=tool_name, error_kind=error_kind, valid=int(valid), observed_at=now, source_id=source_id)
            state = capture(self.manager, "health_detector_states", agent_id=agent_id, detector=detector,
                tool_key=tool_name or "-", error_kind=error_kind, samples=samples, observation_ids=observations,
                last_assessed_id=observation_id if len(samples) >= threshold else previous.values["last_assessed_id"] if previous else None)
            if not valid and len(samples) >= threshold:
                evidence = {"kind": detector, "tool_name": tool_name, "error_kind": error_kind,
                    "observation_ids": observations, "window_seconds": config.observation_window_seconds,
                    "framework_operational_status": "degraded",
                    "facts": ["Repeated structurally classified failures warrant assessment; no health conclusion or intervention is authorized."]}
            task = None
            try:
                await self.manager._records.commit((row, state))
            finally:
                if evidence is not None and row.identity in self.manager._records.index:
                    task = self.schedule_detection(agent_id, observation_id, evidence)
        if task is None:
            return None
        try:
            return await asyncio.shield(task)
        except Exception as error:
            from .service import HealthAssessmentUnavailable

            if not isinstance(error, HealthAssessmentUnavailable):
                raise
            # The retained observation and incident can be retried after a
            # temporary assessment-admission problem. It is not a personal
            # activity failure; the task's callback records sanitized cause.
            return None

    def schedule_detection(self, agent_id, observation_id, evidence):
        current = self.detection_tasks.get(observation_id)
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(self.complete_detection(agent_id, observation_id, evidence),
            context=contextvars.Context(), name=f"att-health-detection-{observation_id}")
        self.detection_tasks[observation_id] = task
        self.active_tasks.add(task)
        def finished(done):
            self.active_tasks.discard(done)
            if self.detection_tasks.get(observation_id) is done:
                self.detection_tasks.pop(observation_id, None)
            if not done.cancelled() and done.exception() is not None:
                self.manager._emit_callback("on_system_event", "health_assessment_admission_deferred",
                    {"agent_id": agent_id, "observation_id": observation_id, "error_type": type(done.exception()).__name__})
        task.add_done_callback(finished)
        return task

    async def complete_detection(self, agent_id, observation_id, evidence):
        subject = HealthSubject(kind="agent", subject_id=agent_id)
        category = {"kind": evidence["kind"], "tool_name": evidence.get("tool_name")}
        if evidence["kind"] == "tool_arguments":
            category["error_kind"] = evidence.get("error_kind")
        fingerprint = self.fingerprint(subject, category)
        await self.record_incident(subject, fingerprint, evidence, occurrence_id=observation_id)
        previous = next((row for row in self.manager._records.snapshot()
            if row.table_name == "audit_runs" and observation_id in row.values["template"].get("evidence", {}).get("observation_ids", ())), None)
        if previous is None and not self.manager._closing:
            return await self.admit(subject, evidence, fingerprint=fingerprint)
        return None

    def resume_detection(self):
        for state in self.manager._records.snapshot():
            if state.table_name != "health_detector_states" or state.values["last_assessed_id"] is None:
                continue
            observation_id = state.values["last_assessed_id"]
            if observation_id not in state.values["observation_ids"]:
                continue
            self.schedule_detection(state.values["agent_id"], observation_id,
                {"kind": state.values["detector"], "tool_name": state.values["tool_key"] if state.values["tool_key"] != "-" else None,
                 "error_kind": state.values["error_kind"], "observation_ids": list(state.values["observation_ids"]),
                 "window_seconds": self.manager.config.health.observation_window_seconds,
                 "framework_operational_status": "degraded", "facts": ["Retained threshold evidence warrants assessment, not intervention."]})

    def sample_semantic_evidence(self, agent_id, source_id):
        if not self.manager.config.health.semantic_detection_enabled or self.semantic_detector is None:
            return
        task = asyncio.create_task(self.inspect_semantic_evidence(agent_id, source_id),
            context=contextvars.Context(), name=f"att-semantic-evidence-{source_id}")
        self.active_tasks.add(task)
        def finished(done):
            self.active_tasks.discard(done)
            if not done.cancelled() and done.exception() is not None:
                self.manager._emit_callback("on_system_event", "semantic_health_detector_failed",
                    {"agent_id": agent_id, "error_type": type(done.exception()).__name__})
        task.add_done_callback(finished)

    async def observe_model(self, session, *, valid, error_kind=None):
        if session.audit_profile is None:
            return await self.observe(session.agent_id, "model_protocol", source_id=session.last_request_id,
                valid=valid, error_kind=error_kind if not valid else None)

    async def observe_tool(self, session, result):
        if session.audit_profile is not None or result.name.startswith("<"):
            return
        if result.status not in {ToolResultStatus.SUCCESS, ToolResultStatus.INVALID_ARGUMENTS}:
            return
        await self.observe(session.agent_id, "tool_arguments",
            source_id=f"{session.last_request_id}:{result.tool_call_id}",
            valid=result.status is ToolResultStatus.SUCCESS, tool_name=result.name,
            error_kind=result.error_kind if result.failed else None)

    def register_semantic_detector(self, detector, evidence_provider):
        if self.manager._active_tool_agent.get() is not None:
            raise PermissionError("Only the Host registers semantic evidence providers.")
        if not callable(detector) or not callable(evidence_provider):
            raise TypeError("A semantic detector and its explicitly authorized evidence provider must be callable.")
        self.semantic_detector, self.semantic_evidence_provider = detector, evidence_provider

    async def inspect_semantic_evidence(self, agent_id, source_id):
        """The Host explicitly supplies permitted evidence; personal windows are never inspected here."""
        if not self.manager.config.health.semantic_detection_enabled or self.semantic_detector is None:
            return
        import asyncio
        import inspect

        async def invoke(function, *args):
            result = await function(*args) if inspect.iscoroutinefunction(function) else await asyncio.to_thread(function, *args)
            return await result if inspect.isawaitable(result) else result
        evidence = await invoke(self.semantic_evidence_provider, agent_id, source_id)
        verdict = await invoke(self.semantic_detector, evidence)
        if verdict is True:
            subject = HealthSubject(kind="agent", subject_id=agent_id)
            await self.admit(subject, {"kind": "semantic", "facts": thaw(evidence), "observation_ids": []})
