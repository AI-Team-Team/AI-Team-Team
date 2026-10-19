"""Relationship boundaries freeze references without rewriting a person's state."""

from contextlib import AsyncExitStack, asynccontextmanager

from ai_team_team.database.persistence.records import DomainRecord, thaw
from ..activity.values import capture
from .membership_staging import MembershipChange


class MembershipMixin:
    @asynccontextmanager
    async def membership_transaction(self, team, *, actor=None):
        """Adapt existing consent/administration workflows to receipt publication."""
        from .base import identity
        actor = actor or self.manager._active_tool_agent.get() or self.manager.root_ai
        async with team.state_lock:
            operation_id = identity("MEMBERSHIP")
            change = MembershipChange(self.manager, team)
            try:
                yield change
                if change.members == team.members and team.proposals == change.proposals:
                    return
                dirty = self.manager._new_dirty_state()
                dirty["proposals"].add(team.team_id)
                dirty["agents"].update(change.registrations)
                dirty["libraries"].update(item.library_id for item in change.registrations.values())
                await change.prepare()
                await self.replace_members(team, change.members, actor=actor, locked=True,
                    dirty=dirty, operation_id=operation_id, registrations=change.registrations,
                    proposals=change.proposals)
            finally:
                await change.release()

    def freeze_departures(self, captured, retained):
        events = {row.values["event_id"]: row for row in (*retained.values(), *captured) if row.table_name == "chat_events"}
        closed = {row.values["interval_id"]: events[row.values["leave_event_id"]].values["sequence"]
                  for row in captured if row.table_name == "membership_intervals" and row.values["leave_event_id"] is not None}
        frozen = []
        for view in retained.values():
            if view.table_name == "chat_personal_views" and view.values["view_kind"] == "live" and view.values["interval_id"] in closed:
                frozen.append(capture(self.manager, "chat_personal_views", view_id=view.values["view_id"],
                    view_kind="frozen", departure_cutoff=closed[view.values["interval_id"]]))
        return frozen

    async def replace_members(self, team, members, *, actor=None, locked=False, dirty=None, operation_id=None, mail_specs=(), registrations=None, proposals=None):
        """Internal accepted-consent adapter; callers retain their domain authority checks."""
        if locked:
            return await self._replace_members_locked(team, members, actor=actor, dirty=dirty, operation_id=operation_id, mail_specs=mail_specs, registrations=registrations, proposals=proposals)
        async with team.state_lock:
            return await self._replace_members_locked(team, members, actor=actor, dirty=dirty, operation_id=operation_id, mail_specs=mail_specs, registrations=registrations, proposals=proposals)

    async def _replace_members_locked(self, team, members, *, actor=None, dirty=None, operation_id=None, mail_specs=(), registrations=None, proposals=None):
        manager = self.manager
        registrations = registrations or {}
        agents = {**manager._agents_by_id, **{owner: item.agent for owner, item in registrations.items()}}
        actor = self.actor(actor)
        if (manager.teams.get(team.team_id) is not team or team.team_kind != "ordinary"
                or getattr(team, "_lifecycle_state", "active") != "active" or getattr(team, "_publication_pending", False)):
            raise PermissionError("Membership changes require a live ordinary AgentTeam.")
        identifiers = tuple(member.agent_id for member in members)
        if not set(registrations).issubset(identifiers):
            raise ValueError("A staged Agent registration must be part of the accepted membership.")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate membership identities are not allowed.")
        for member in members:
            if agents.get(member.agent_id) is not member or member.lifecycle_state != "active":
                raise PermissionError("Membership requires this manager's registered person.")
        async with AsyncExitStack() as gates:
            joining = set(identifiers) - {member.agent_id for member in team.members}
            for identifier in sorted(joining):
                await gates.enter_async_context(agents[identifier].lifecycle_lock)
            await gates.enter_async_context(manager._activity.lock)
            manager._activity.check_open()
            actor = self.actor(actor)
            for identifier in identifiers:
                if identifier not in registrations:
                    manager._activity.require_agent(identifier)
            stream = self.stream_for_team(team)
            cursor = thaw(stream.values)
            opened = {row.values["agent_id"]: row for row in self.rows("membership_intervals")
                      if row.values["team_id"] == team.team_id and row.values["leave_event_id"] is None}
            records = []
            for owner in sorted(set(opened) ^ set(identifiers)):
                from .base import identity
                joining = owner in identifiers
                event = capture(manager, "chat_events", event_id=identity("CE"), stream_id=cursor["stream_id"],
                    sequence=cursor["next_position"], event_kind="join" if joining else "leave", actor_agent_id=owner,
                    created_at=self.clock.wall_time())
                records.append(event)
                cursor["next_position"] += 1
                if joining:
                    records.append(capture(manager, "membership_intervals", interval_id=identity("MI"), team_id=team.team_id,
                        agent_id=owner, stream_id=cursor["stream_id"], join_event_id=event.values["event_id"]))
                else:
                    records.append(capture(manager, "membership_intervals", interval_id=opened[owner].values["interval_id"],
                        leave_event_id=event.values["event_id"]))
            if cursor["next_position"] != stream.values["next_position"]:
                cursor["state_version"] = stream.version + 1
                records.append(DomainRecord.capture("chat_streams", cursor))
            records.extend(self.freeze_departures(records, manager._records.index))
            dirty = dirty or manager._new_dirty_state()
            dirty["teams"].add(team.team_id)
            dirty["_relationships_supplied"] = True
            from .base import identity
            operation_id = operation_id or identity("MEMBERSHIP")
            mail_ids, notice_ids = [], ()
            try:
                for owner, kind, payload in mail_specs:
                    mail_ids.append((owner, manager._inbox.notify(owner, kind, payload)))
                    dirty["agent_inboxes"].add(owner)
                arrivals, notice_ids = manager._activity.mail_records(dirty["agent_inboxes"])
                return await manager._records.commit((*records, *arrivals), dirty=dirty, notifications=notice_ids,
                    operation_id=operation_id, team_memberships={team.team_id: identifiers},
                    agent_registrations=registrations, team_proposals={team.team_id: proposals} if proposals is not None else None)
            finally:
                if operation_id not in manager._records.receipts:
                    for owner, mail_id in mail_ids:
                        agent = manager._agents_by_id[owner]
                        with agent.inbox_lock:
                            agent.agent_inbox[:] = [mail for mail in agent.agent_inbox if mail["message_id"] != mail_id]
                for notice_id in notice_ids:
                    if ("agent_notifications", (notice_id,)) in manager._records.index:
                        manager._activity.schedule_notice(notice_id)
