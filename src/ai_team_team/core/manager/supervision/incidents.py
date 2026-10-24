"""Durable deduplication and explicit acknowledgement, independent of mail state."""

import hashlib
import json

from ai_team_team.core.health import HealthSubject
from ai_team_team.database.persistence.records import thaw

from ..activity.values import capture, identifier


class HealthIncidentMixin:
    @staticmethod
    def fingerprint(subject, evidence):
        return hashlib.sha256(json.dumps({"subject": subject.model_dump(mode="json"), "evidence": evidence},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def record_incident(self, subject, fingerprint, evidence, *, occurrence_id, delivery_mode=None):
        if delivery_mode not in {None, "none", "queue", "wake"}:
            raise ValueError("Incident delivery mode must be none, queue, or wake.")
        async with self.incident_lock:
            existing_event = self.manager._records.index.get(("health_incident_events", (occurrence_id,)))
            if existing_event is not None:
                existing = self.manager._records.index[("health_incidents", (existing_event.values["incident_id"],))]
                if (existing_event.values["event_kind"] != "occurrence" or existing.values["fingerprint"] != fingerprint
                        or HealthSubject.from_record(existing.values) != subject):
                    raise ValueError("An incident occurrence identity cannot be rebound to different evidence ownership.")
                return existing
            fields = subject.record_fields()
            previous = next((row for row in self.manager._records.snapshot() if row.table_name == "health_incidents"
                and row.values["fingerprint"] == fingerprint and all(row.values[key] == value for key, value in fields.items())), None)
            now = self.manager._activity.clock.wall_time()
            incident_id = previous.values["incident_id"] if previous else identifier("INCIDENT")
            count = previous.values["occurrence_count"] + 1 if previous else 1
            retained = thaw(previous.values["evidence"]) if previous else {}
            retained.update(latest=evidence)
            retained.pop("claim", None)
            if delivery_mode is not None:
                retained["delivery"] = {"occurrence_count": count, "mode": delivery_mode}
            row = capture(self.manager, "health_incidents", incident_id=incident_id, **fields,
                fingerprint=fingerprint, occurrence_count=count,
                first_at=previous.values["first_at"] if previous else now,
                latest_at=max(now, previous.values["latest_at"]) if previous else now,
                evidence=retained, status="pending")
            event = capture(self.manager, "health_incident_events", event_id=occurrence_id,
                incident_id=incident_id, event_kind="occurrence", occurrence_count=count,
                actor_agent_id=None, details={"kind": evidence.get("kind", "assessment")}, created_at=now)
            await self.manager._records.commit((row, event), allow_closing=True)
        self.manager._emit_callback("on_system_event", "health_incident_recorded",
            {"incident_id": incident_id, "subject": subject.model_dump(mode="json"), "occurrence_count": count})
        pending = sum(item.table_name == "health_incidents" and item.values["status"] != "acknowledged"
                      for item in self.manager._records.snapshot())
        if pending >= self.manager.config.audit_unknown_soft_threshold:
            self.manager._emit_callback("on_system_event", "health_incident_soft_threshold", {"pending": pending})
        return row

    def incident_handler(self, subject):
        if subject.kind == "agent_team":
            team = self.manager.teams.get(subject.subject_id)
            return team.organizational_parent if team is not None else None
        return None

    def authorize_incident(self, row, actor=None, *, observe=False):
        current = self.manager._active_tool_agent.get()
        if current is not None and actor is not None and current is not actor:
            raise PermissionError("A tool cannot override its current incident-handling Agent.")
        if current is None and actor is None and self.manager._activity.current.get() is None:
            return None
        actor = current if current is not None else actor
        if actor is None or self.manager._agents_by_id.get(actor.agent_id) is not actor or actor.lifecycle_state != "active":
            raise PermissionError("Health incident access requires a current registered authority.")
        subject = HealthSubject.from_record(row.values)
        if observe and subject.kind == "agent" and subject.subject_id == actor.agent_id:
            return actor
        principal = self.incident_handler(subject)
        team = self.manager._active_team.get()
        if principal is not None and (principal.kind == "agent" and principal.principal_id == actor.agent_id
                or principal.kind == "agent_team" and team is not None and team.team_id == principal.principal_id
                and getattr(team, "_lifecycle_state", "active") == "active" and actor in team.members):
            return actor
        if observe and subject.kind == "agent_team" and team is not None and team.team_id == subject.subject_id and actor in team.members:
            return actor
        raise PermissionError("Only the Host or the subject's actual designated parent may acknowledge this incident.")

    def inspect_incident(self, incident_id, actor=None):
        row = self.manager._records.index[("health_incidents", (incident_id,))]
        self.authorize_incident(row, actor, observe=True)
        return thaw(row.values)

    async def claim_incident(self, incident_id, actor=None):
        async with self.incident_lock:
            row = self.manager._records.index[("health_incidents", (incident_id,))]
            owner = self.authorize_incident(row, actor)
            if row.values["status"] == "acknowledged":
                return {"status": "ALREADY_ACKNOWLEDGED", "incident_id": incident_id}
            evidence = thaw(row.values["evidence"])
            claim = evidence.get("claim")
            if row.values["status"] == "claimed" and claim is not None:
                if claim["agent_id"] != (owner.agent_id if owner else None):
                    raise PermissionError("Another authority is currently processing this incident.")
                return {"status": "CLAIMED", **claim}
            claim = {"token": identifier("HEALTH-CLAIM"), "agent_id": owner.agent_id if owner else None,
                "occurrence_count": row.values["occurrence_count"]}
            evidence["claim"] = claim
            await self.manager._records.commit((capture(self.manager, "health_incidents", incident_id=incident_id,
                status="claimed", evidence=evidence), capture(self.manager, "health_incident_events",
                event_id=claim["token"], incident_id=incident_id, event_kind="claimed",
                occurrence_count=row.values["occurrence_count"], actor_agent_id=claim["agent_id"],
                details={}, created_at=self.manager._activity.clock.wall_time())),
                authority_check=lambda: self.authorize_incident(row, actor))
            return {"status": "CLAIMED", **claim}

    async def acknowledge_incident(self, incident_id, occurrence_count, *, actor=None, claim_token=None):
        if type(occurrence_count) is not int or occurrence_count < 1:
            raise ValueError("Acknowledgement requires an explicit positive occurrence generation.")
        async with self.incident_lock:
            row = self.manager._records.index[("health_incidents", (incident_id,))]
            owner = self.authorize_incident(row, actor)
            evidence = thaw(row.values["evidence"])
            claim = evidence.get("claim")
            if owner is not None and (row.values["status"] != "claimed" or claim is None
                    or claim["agent_id"] != owner.agent_id or claim["token"] != claim_token):
                raise PermissionError("The handling Agent must present its exact processing claim.")
            if row.values["occurrence_count"] != occurrence_count:
                return {"status": "STALE", "occurrence_count": row.values["occurrence_count"]}
            evidence.pop("claim", None)
            await self.manager._records.commit((capture(self.manager, "health_incidents", incident_id=incident_id,
                status="acknowledged", evidence=evidence), capture(self.manager, "health_incident_events",
                event_id=identifier("HEALTH-ACK"), incident_id=incident_id, event_kind="acknowledged",
                occurrence_count=occurrence_count, actor_agent_id=owner.agent_id if owner else None,
                details={}, created_at=self.manager._activity.clock.wall_time())),
                authority_check=lambda: self.authorize_incident(row, actor))
            return {"status": "ACKNOWLEDGED", "incident_id": incident_id}

    async def release_claims(self, agent_id, *, incident_id=None, claim_token=None):
        async with self.incident_lock:
            updates = []
            for row in self.manager._records.snapshot():
                if row.table_name != "health_incidents" or row.values["status"] != "claimed":
                    continue
                if incident_id is not None and row.values["incident_id"] != incident_id:
                    continue
                evidence = thaw(row.values["evidence"])
                if evidence.get("claim", {}).get("agent_id") != agent_id:
                    continue
                if claim_token is not None and evidence.get("claim", {}).get("token") != claim_token:
                    continue
                evidence.pop("claim", None)
                updates.append(capture(self.manager, "health_incidents", incident_id=row.values["incident_id"],
                    status="pending", evidence=evidence))
                updates.append(capture(self.manager, "health_incident_events", event_id=identifier("HEALTH-RELEASE"),
                    incident_id=row.values["incident_id"], event_kind="released",
                    occurrence_count=row.values["occurrence_count"], actor_agent_id=agent_id,
                    details={}, created_at=self.manager._activity.clock.wall_time()))
            if updates:
                with self.manager._resources.settlement():
                    await self.manager._records.commit(updates, allow_closing=True)

    async def deliver_incident(self, incident, mode):
        if mode == "none":
            return
        subject = HealthSubject.from_record(incident.values)
        handler = self.incident_handler(subject)
        if handler is None:
            self.manager._emit_callback("on_system_event", "root_health_incident",
                {"incident_id": incident.values["incident_id"], "subject": subject.model_dump(mode="json")})
            return
        owners = [agent.agent_id for agent in self.manager._governance.electorate(handler)]
        for owner in owners:
            async with self.incident_lock:
                current = self.manager._records.index[incident.identity]
                evidence = thaw(current.values["evidence"])
                notices = evidence.setdefault("notices", {})
                previous = notices.get(owner)
                if previous and previous["occurrence_count"] == current.values["occurrence_count"]:
                    event = self.manager._memory.events[previous["event_id"]]
                else:
                    event = self.manager._memory.record_event("health_incident", agent=self.manager._agents_by_id[owner],
                        payload={"incident_id": current.values["incident_id"], "occurrence_count": current.values["occurrence_count"],
                                 "delivery_mode": mode, "handler": handler.model_dump(mode="json"),
                                 "subject": subject.model_dump(mode="json")},
                        persist=False, inherit_context=False)
                    notices[owner] = {"event_id": event.event_id, "occurrence_count": current.values["occurrence_count"], "mode": mode}
                    dirty = self.manager._new_dirty_state()
                    dirty["memory_events"].add(event.event_id)
                    operation_id = f"HEALTH-NOTICE-{current.values['incident_id']}-{owner}-{current.values['occurrence_count']}"
                    try:
                        await self.manager._records.commit((capture(self.manager, "health_incidents",
                            incident_id=current.values["incident_id"], evidence=evidence),), dirty=dirty,
                            operation_id=operation_id, allow_closing=True)
                    finally:
                        if operation_id not in self.manager._records.receipts:
                            self.manager._memory.discard_unpersisted_event(event.event_id)
            if not self.manager._closing:
                await self.manager._activity.deliver_system_event(event, schedule=mode == "wake")

    def resume_incident_delivery(self):
        """Recover the receipt-owned alert outbox without rerunning its assessment."""
        import asyncio
        import contextvars

        for row in self.manager._records.snapshot():
            if row.table_name != "health_incidents" or row.values["status"] == "acknowledged":
                continue
            delivery = row.values["evidence"].get("delivery")
            if delivery is None or delivery["occurrence_count"] != row.values["occurrence_count"] or delivery["mode"] == "none":
                continue
            key = (row.values["incident_id"], row.values["occurrence_count"])
            previous = self.incident_delivery_tasks.get(key)
            if previous is not None and not previous.done():
                continue
            task = asyncio.create_task(self.deliver_incident(row, delivery["mode"]),
                context=contextvars.Context(), name=f"att-health-outbox-{key[0]}")
            self.incident_delivery_tasks[key] = task
            self.active_tasks.add(task)

            def finished(done, identity=key):
                self.active_tasks.discard(done)
                if self.incident_delivery_tasks.get(identity) is done:
                    self.incident_delivery_tasks.pop(identity, None)
                if not done.cancelled() and done.exception() is not None:
                    self.manager._emit_callback("on_system_event", "health_incident_delivery_deferred",
                        {"incident_id": identity[0], "error_type": type(done.exception()).__name__})

            task.add_done_callback(finished)
