"""Host assessment admission and explicitly authorized technical incident handling."""

from contextlib import asynccontextmanager


class HealthAPI:
    def _require_health_host(self):
        if self._active_tool_agent.get() is not None or self._activity.current.get() is not None:
            raise PermissionError("Only the Host may admit, cancel, or configure an assessment.")

    async def request_health_assessment(self, subject, evidence):
        self._require_health_host()
        return await self.supervisor.admit(subject, evidence)

    async def wait_for_health_assessment(self, audit_id):
        self._require_health_host()
        return await self.supervisor.wait(audit_id)

    async def cancel_health_assessment(self, audit_id):
        self._require_health_host()
        await self.supervisor.cancel(audit_id)

    def register_semantic_health_detector(self, detector, *, evidence_provider):
        self._require_health_host()
        self.supervisor.register_semantic_detector(detector, evidence_provider)

    def inspect_health_incident(self, incident_id, *, actor=None):
        return self.supervisor.inspect_incident(incident_id, actor)

    async def claim_health_incident(self, incident_id, *, actor=None):
        return await self.supervisor.claim_incident(incident_id, actor)

    async def acknowledge_health_incident(self, incident_id, occurrence_count, *, actor=None, claim_token=None):
        return await self.supervisor.acknowledge_incident(incident_id, occurrence_count, actor=actor, claim_token=claim_token)

    async def clear_health_incidents(self, incident_ids):
        """Host clears pending attention explicitly without deleting retained evidence."""
        self._require_health_host()
        results = []
        for incident_id in incident_ids:
            row = self.inspect_health_incident(incident_id)
            results.append(await self.acknowledge_health_incident(incident_id, row["occurrence_count"]))
        return results

    @asynccontextmanager
    async def handle_health_incident(self, incident_id, *, actor=None):
        claim = await self.claim_health_incident(incident_id, actor=actor)
        try:
            yield claim
        except BaseException:
            if claim.get("token") is not None:
                await self.supervisor.release_claims(claim.get("agent_id"), incident_id=incident_id, claim_token=claim["token"])
            raise

    async def report_integrity_fault(self, subject, fault_code, *, protect):
        """A trusted deterministic guard supplies immediate, fault-specific protection."""
        self._require_health_host()
        import inspect
        if type(fault_code) is not str or not fault_code.strip():
            raise ValueError("A confirmed integrity fault requires a nonempty stable fault code.")
        subject = self.supervisor.require_subject(subject)
        if not callable(protect) or inspect.iscoroutinefunction(protect):
            raise TypeError("Integrity protection must be an immediate synchronous guard action.")
        protection_error = None
        try:
            result = protect()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if close:
                    close()
                raise TypeError("Integrity protection cannot wait on external asynchronous work.")
        except Exception as error:
            protection_error = error
        fingerprint = self.supervisor.fingerprint(subject, {"kind": "integrity", "fault_code": fault_code})
        from ..activity.values import identifier
        with self._resources.settlement():
            incident = await self.supervisor.record_incident(subject, fingerprint,
                {"kind": "integrity", "fault_code": fault_code, "protection_applied": protection_error is None,
                 **({"protection_error_type": type(protection_error).__name__} if protection_error is not None else {})},
                occurrence_id=identifier("INTEGRITY"), delivery_mode="wake")
        await self.supervisor.deliver_incident(incident, "wake")
        if protection_error is not None:
            raise protection_error
        return self.supervisor.inspect_incident(incident.values["incident_id"])
