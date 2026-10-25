"""ACL publication and affected-person notices share one authoritative receipt."""

from ai_team_team.core.exceptions import ToolPermissionError
from ..activity.lifecycle_notices import membership_notices
from ..activity.values import identifier


class LibraryPermissionMixin:
    async def change_permission(self, owner_team, lib_id, path, target_team_id, permission):
        manager = self.manager
        async with self.permission_lock, manager._activity.lock:
            manager._activity.check_open()
            library = manager.libraries[lib_id]
            target = manager.teams.get(target_team_id)
            def authorize():
                manager._topology.require_available(owner_team)
                manager._topology.require_available(target)
                actor = manager._active_tool_agent.get()
                if library.library_kind != "team" or library.owner_team_id != owner_team.team_id:
                    raise ToolPermissionError("Only the live owning AgentTeam may change this team-library ACL.")
                if actor is not None and (manager._active_team.get() is not owner_team or actor not in owner_team.members
                        or manager._activity.require_agent(actor.agent_id) is not actor):
                    raise ToolPermissionError("The ACL actor lost its current owning-team authority.")
            authorize()
            clean_path = manager.normalize_library_path(path)
            current = manager.library_permissions.get(lib_id, {})
            candidate = {key: dict(value) for key, value in current.items()}
            if permission is None:
                if candidate.get(clean_path, {}).pop(target_team_id, None) is None:
                    return False
            else:
                if permission not in {"READ", "WRITE"}:
                    raise ValueError("permission must be READ or WRITE.")
                candidate.setdefault(clean_path, {})[target_team_id] = permission
            operation = identifier("ACL")
            records, notices, events = membership_notices(manager, (member.agent_id for member in target.members),
                team_ids=(target_team_id,), source_id=operation, reason="library_permission_changed",
                event_type="permission_changed", classification="permission",
                metadata={"library_id": lib_id, "path": clean_path, "permission": permission})
            dirty = manager._new_dirty_state()
            dirty["permissions"].add(lib_id)
            dirty["memory_events"].update(events)
            try:
                await manager._records.commit(records, dirty=dirty, notifications=notices,
                    operation_id=operation, permission_changes={lib_id: candidate}, authority_check=authorize)
            finally:
                if operation in manager._records.receipts:
                    for notice_id in notices:
                        manager._activity.schedule_notice(notice_id)
                else:
                    for event_id in events:
                        manager._memory.discard_unpersisted_event(event_id)
            return True
