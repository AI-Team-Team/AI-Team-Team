"""A retained Host-only death closes relationships without erasing a person."""

import asyncio
import contextvars
from contextlib import AsyncExitStack

from ai_team_team.core.exceptions import StateRestoreError, ToolPermissionError
from ai_team_team.database.persistence.receipts import settle_commit

from ..activity.values import capture, identifier


def require_host(manager):
    manager._resources.check_authority()
    if manager._active_tool_agent.get() is not None or manager._activity.current.get() is not None or manager._executions.current.get() is not None:
        raise ToolPermissionError("Only the Host may change an ordinary Agent's retained death state.")


def preview(manager, agent_id):
    require_host(manager)
    agent = manager._agents_by_id[agent_id]
    if agent is manager.root_ai:
        raise ValueError("The Root Agent is protected from death.")
    if manager.supervisor.is_supervisory_agent(agent_id):
        raise ValueError("Temporary audit identities use their scoped teardown protocol.")
    return {"agent_id": agent_id, "state": agent.lifecycle_state,
        "membership_team_ids": sorted(team.team_id for team in manager.teams.values() if agent in team.members),
        "unresolved_execution_ids": sorted(row.values["execution_id"] for row in manager._records.snapshot()
            if row.table_name == "executions" and row.values["agent_id"] == agent_id and row.values["status"] in {"queued", "running"}),
        "warning": "Death is terminal and retains personal history and private artifacts. Live external operations may not acknowledge stopping; unconfirmed consequences remain recorded."}


async def mark_dead(manager, agent_id, *, confirm):
    require_host(manager)
    manager._activity.check_open()
    description = preview(manager, agent_id)
    if type(confirm) is not bool or not confirm:
        raise ValueError(description["warning"] + " Explicit confirm=True is required.")
    registry = manager._agent_registry
    task = registry.death_tasks.get(agent_id)
    if task is None:
        task = asyncio.create_task(_transition(manager, agent_id), context=contextvars.Context(), name=f"att-agent-death-{agent_id}")
        registry.death_tasks[agent_id] = task
        def finished(done):
            registry.death_tasks.pop(agent_id, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
    return await settle_commit(task)


async def _transition(manager, owner):
    agent = manager._agents_by_id[owner]
    if agent.lifecycle_state == "dead":
        return {"agent_id": owner, "state": "dead", "tasks": []}
    registry = manager._agent_registry
    with manager._resources.topology_mutation():
        manager._activity.check_open()
        generation = manager._resources.generation
        registry.lifecycle_pending.add(owner)
    committed = False
    event = None
    tasks = []
    try:
        while True:
            outcomes = manager._executions.pending_owner_outcomes(owner)
            if outcomes:
                # These are already returned facts, never external waits. Keep
                # the live owner and memberships until their exact receipts.
                await settle_commit(asyncio.gather(*outcomes))
            teams = sorted((team for team in manager.teams.values() if agent in team.members), key=lambda team: team.team_id)
            async with AsyncExitStack() as locks:
                for team in teams:
                    await locks.enter_async_context(team.state_lock)
                await locks.enter_async_context(agent.lifecycle_lock)
                await locks.enter_async_context(manager._topology.transition_lock)
                await locks.enter_async_context(manager._activity.lock)
                if any(agent in team.members and team not in teams for team in manager.teams.values()):
                    continue
                if manager._executions.pending_owner_outcomes(owner):
                    # An outcome can arrive while team/lifecycle locks are
                    # queued. Release every domain lock before settling it.
                    continue
                manager._activity.check_open()
                if manager._agents_by_id.get(owner) is not agent or manager._resources.generation != generation:
                    raise StateRestoreError("The Agent lifecycle belongs to an obsolete runtime generation.")
                with manager._topology.reserve_agent_parent(agent):
                    event = manager._memory.record_event("agent_lifecycle_changed", agent=agent,
                        payload={"lifecycle_state": "dead"}, persist=False, inherit_context=False, staged=True)
                    records, changes = manager._topology.parent_loss_records(agent, event.event_id)
                    memberships = {}
                    for team in teams:
                        memberships[team.team_id] = tuple(member.agent_id for member in team.members if member is not agent)
                        stream = manager._messaging.stream_for_team(team)
                        leave, cursor = manager._messaging.event(stream, "leave", agent)
                        records.extend((leave, cursor))
                        records.extend(capture(manager, "membership_intervals", interval_id=row.values["interval_id"],
                            leave_event_id=leave.values["event_id"]) for row in manager._records.snapshot()
                            if row.table_name == "membership_intervals" and row.values["agent_id"] == owner
                            and row.values["team_id"] == team.team_id and row.values["leave_event_id"] is None)
                    records.extend(manager._messaging.freeze_departures(records, manager._records.index))
                    for row in manager._records.snapshot():
                        if row.values.get("agent_id") != owner:
                            continue
                        if row.table_name == "activity_admissions" and row.values["disposition"] == "admitted":
                            records.append(capture(manager, row.table_name, admission_id=row.values["admission_id"], disposition="cancelled"))
                        elif row.table_name == "agent_activities":
                            records.append(capture(manager, row.table_name, agent_id=owner,
                                admission_id=None, availability="closing"))
                        elif row.table_name == "activity_invocations" and row.values["boundary_at"] is None:
                            records.append(capture(manager, row.table_name, invocation_id=row.values["invocation_id"],
                                boundary_at=max(manager._activity.clock.wall_time(), row.values["started_at"]), interrupted=1))
                        elif row.table_name == "sleep_plans" and row.values["status"] == "active":
                            records.append(capture(manager, row.table_name, sleep_id=row.values["sleep_id"], status="cancelled"))
                        elif row.table_name == "notification_suppression" and row.values["status"] == "active":
                            records.append(capture(manager, row.table_name, preference_id=row.values["preference_id"],
                                status="removed", remaining_seconds=manager._activity.suppression_remaining(row),
                                sampled_at=manager._activity.clock.wall_time()))
                    dirty = manager._new_dirty_state()
                    dirty["agents"].add(owner)
                    dirty["libraries"].add(agent.private_doc_library_id)
                    dirty["memory_events"].add(event.event_id)
                    dirty["teams"].update((*memberships, *changes))
                    dirty["_relationships_supplied"] = True
                    from ..activity.lifecycle_notices import membership_notices
                    affected = {member.agent_id for team in teams for member in team.members if member is not agent}
                    notices, notice_ids, notice_events = membership_notices(manager, affected,
                        team_ids=memberships, source_id=event.event_id, reason="member_died")
                    dirty["memory_events"].update(notice_events)
                    operation = f"DEATH-{event.event_id}"
                    try:
                        await manager._records.commit((*records, *notices), dirty=dirty, operation_id=operation,
                            agent_lifecycles={owner: "dead"}, team_memberships=memberships, team_parents=changes,
                            notifications=notice_ids)
                    finally:
                        committed = operation in manager._records.receipts
                        if committed:
                            for notice_id in notice_ids:
                                manager._activity.schedule_notice(notice_id)
                        else:
                            for event_id in notice_events:
                                manager._memory.discard_unpersisted_event(event_id)
                break
    finally:
        try:
            if committed:
                # A receipt survives caller cancellation or a failed handoff.
                # Stop personal and external waits after releasing domain locks.
                manager._activity.stop_dead_owner(owner)
                try:
                    tasks = await manager._executions.stop_retained_owner(agent)
                finally:
                    await manager.supervisor.release_claims(owner)
        finally:
            registry.lifecycle_pending.discard(owner)
            manager._executions.wakeup.set()
            if not committed and event is not None:
                manager._memory.discard_unpersisted_event(event.event_id)
            if not committed:
                # Timers and addressed arrivals can reach this temporary fence.
                # Resume from their original deadlines after withdrawing it.
                manager._activity.resume_owner_activity(owner)
    manager._emit_callback("on_system_event", "agent_lifecycle_changed",
        {"agent_id": owner, "state": "dead", "library_id": agent.private_doc_library_id})
    return {"agent_id": owner, "state": "dead", "tasks": [task.model_dump(mode="json") for task in tasks]}

