"""Receipt-bound archive finalization, without granting AI dissolution authority."""

from ..activity.values import capture
from .base import identity


class ArchiveMixin:
    async def close_team_conversation(self, team_id):
        """Host finalizes a leaf; institutional parent-loss policy is a later adapter."""
        manager = self.manager
        if manager._active_tool_agent.get() is not None or manager._activity.current.get() is not None:
            raise PermissionError("Only the Host may finalize a dissolved conversation.")
        team = manager.teams.get(team_id)
        if team is None or team.team_kind != "ordinary":
            raise ValueError("An ordinary AgentTeam is required.")
        async with team.discussion_lock, team.state_lock, manager._topology.transition_lock, manager._activity.lock:
            manager._activity.check_open()
            if manager.teams.get(team_id) is not team:
                raise ValueError("The AgentTeam changed while archive finalization was waiting.")
            if getattr(team, "_lifecycle_state", "active") == "dissolved":
                return None
            with manager._topology.reserve_transition(team):
                return await self._close_reserved_conversation(team)

    async def _close_reserved_conversation(self, team):
        manager = self.manager
        team_id = team.team_id
        with manager._topology_lock:
            if any(child.parent_team is team and getattr(child, "_lifecycle_state", "active") == "active"
                   for child in manager.teams.values()):
                raise ValueError("Resolve live child-parent relationships before finalizing dissolution.")
        stream = self.stream_for_team(team)
        event, cursor = self.event(stream, "dissolve", None)
        records = [event, cursor]
        records.extend(capture(manager, "membership_intervals", interval_id=row.values["interval_id"],
                               leave_event_id=event.values["event_id"])
                       for row in self.rows("membership_intervals") if row.values["team_id"] == team_id
                       and row.values["leave_event_id"] is None)
        records.extend(self.freeze_departures(records, manager._records.index))
        dirty = manager._new_dirty_state()
        dirty["teams"].add(team_id)
        dirty["_relationships_supplied"] = True
        receipt = await manager._records.commit(records, dirty=dirty, operation_id=identity("DISSOLUTION"),
            team_memberships={team_id: ()}, team_lifecycles={team_id: "dissolved"})
        manager._emit_callback("on_system_event", "team_conversation_closed", {"team_id": team_id})
        return receipt
