"""Trusted relationship outboxes do not edit a person's memory or mail choices."""

from .values import Session, capture, identifier


def membership_notices(manager, owners, *, team_ids, source_id, reason, event_type="membership_changed", classification="membership", metadata=None):
    records, identifiers, events = [], [], []
    for owner in sorted(set(owners)):
        agent = manager._agents_by_id.get(owner)
        if agent is None or agent.lifecycle_state != "active":
            continue
        event = manager._memory.record_event(event_type, agent=agent,
            payload={"team_ids": sorted(team_ids), "source_id": source_id, "reason": reason, **(metadata or {})},
            persist=False, inherit_context=False, staged=True)
        events.append(event.event_id)
        notice_id = f"NOTICE-{event.event_id}"
        marker = manager._records.index.get(("agent_activities", (owner,)))
        arrival = marker.values["arrival_generation"] + 1 if marker else 1
        session = manager._activity.sessions.get(owner) or Session(owner, identifier("ADMISSION"),
            manager._resources.generation, active=False, intent="idle")
        records.extend((capture(manager, "agent_notifications", notification_id=notice_id, agent_id=owner,
            source_kind="system_event", system_event_id=event.event_id, classification=classification,
            deduplication_key=f"{classification}:{source_id}:{owner}", arrival_generation=arrival,
            created_at=manager._activity.clock.wall_time()), manager._activity.marker(session, arrival_generation=arrival)))
        identifiers.append(notice_id)
    return records, identifiers, events
