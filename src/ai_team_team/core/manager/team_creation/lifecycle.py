"""Managed teardown of completed short-lived AgentTeams."""

import asyncio
import os
import shutil
import uuid

from ...team import AgentTeam


class TeamLifecycleMixin:
    async def dissolve_supervisory_team(
        self, team: AgentTeam, *, persist: bool = True
    ) -> None:
        """Remove an audit-scoped AT, even if a failed writer prevents journal commits."""
        manager = self.manager
        if persist:
            await manager.flush_state()
        async with manager._runtime_gate:
            if manager.teams.get(team.team_id) is not team or team.team_kind != "supervisory":
                raise ValueError("Only a registered supervisory AgentTeam can be dissolved.")
            if team.is_running or team.discussion_lock.locked() or team.child_teams:
                raise RuntimeError("The supervisory AgentTeam is still active.")
            if team.message_inbox or team.proposals:
                raise RuntimeError("The supervisory AgentTeam has unresolved business state.")
            members = tuple(team.members)
            member_ids = {agent.agent_id for agent in members}
            if any(
                manager._agents_by_id.get(agent.agent_id) is not agent
                or agent.lock.locked()
                or agent.lifecycle_state != "active"
                for agent in members
            ):
                raise RuntimeError("A supervisory Agent is unavailable or still running.")
            if any(
                other is not team and (
                    team is other.parent_team
                    or any(member.agent_id in member_ids for member in other.members)
                    or (hasattr(other.creator, "agent_id") and other.creator.agent_id in member_ids)
                )
                for other in manager.teams.values()
            ):
                raise RuntimeError("A supervisory Agent or team is referenced by another team.")
            if any(
                team.team_id in {request.sender_team_id, request.recipient_team_id}
                or request.initiated_by_agent_id in member_ids
                for request in manager.broker.communication_requests.values()
            ) or any(
                team.team_id in {agreement.source_team_id, agreement.target_team_id}
                for agreement in manager.broker.agreements.values()
            ) or any(
                team.team_id in {message.sender_team_id, message.recipient_team_id}
                or message.initiated_by_agent_id in member_ids
                for message in manager.broker.peer_messages.values()
            ):
                raise RuntimeError("The supervisory AgentTeam has communication references.")
            if any(
                request.initiator_agent_id in member_ids
                or request.creator_id == team.team_id
                or request.creator_id in member_ids
                or team.team_id == request.parent_team_id
                or member_ids.intersection(request.invitee_agent_ids)
                for request in manager._formations.requests.values()
            ):
                raise RuntimeError("The supervisory AgentTeam has formation references.")

            library_ids = {f"DL-{team.team_id}"} | {
                manager.get_private_library_id(agent.agent_id) for agent in members
            }
            libraries = {lib_id: manager.libraries[lib_id] for lib_id in library_ids}
            if any(
                lib_id in manager.library_links
                and manager.library_links[lib_id]
                for lib_id in library_ids
            ) or any(
                target.get("lib_id") in library_ids
                for links in manager.library_links.values()
                for target in links.values()
            ):
                raise RuntimeError("The supervisory AgentTeam has managed DocLib links.")

            moved: list[tuple[str, str]] = []
            event = None
            committed = False
            cancelled = False
            try:
                for library in libraries.values():
                    if not os.path.exists(library.root_dir):
                        continue
                    trash = os.path.join(
                        os.path.dirname(library.root_dir),
                        f".{library.lib_id}-audit-retire-{uuid.uuid4().hex}",
                    )
                    os.replace(library.root_dir, trash)
                    moved.append((library.root_dir, trash))
                if persist:
                    event = manager._memory.record_event(
                        "supervisory_team_dissolved",
                        team=team,
                        payload={
                            "team_id": team.team_id,
                            "auditor_agent_ids": sorted(member_ids),
                        },
                        persist=False,
                        inherit_context=False,
                    )
                    dirty = manager._new_dirty_state()
                    dirty["deleted_teams"].add(team.team_id)
                    dirty["deleted_agents"].update(member_ids)
                    dirty["deleted_libraries"].update(library_ids)
                    dirty["memory_events"].add(event.event_id)
                    commit_task = asyncio.create_task(manager._commit_dirty_state(dirty))
                    while True:
                        try:
                            await asyncio.shield(commit_task)
                            break
                        except asyncio.CancelledError:
                            cancelled = True
                            if commit_task.done():
                                commit_task.result()
                                break
                committed = True
            except BaseException:
                if not committed:
                    if event is not None:
                        manager._memory.discard_unpersisted_event(event.event_id)
                    for original, trash in reversed(moved):
                        if os.path.exists(trash):
                            os.replace(trash, original)
                raise

            with manager._topology_lock:
                manager.teams.pop(team.team_id)
                manager._team_parent_map.pop(team.team_id, None)
                for agent in members:
                    manager.agents.pop(agent.name, None)
                    manager._agents_by_id.pop(agent.agent_id, None)
                for lib_id in library_ids:
                    manager.libraries.pop(lib_id, None)
                    manager._library_files.pop(lib_id, None)
                    manager.library_permissions.pop(lib_id, None)
                    manager.library_links.pop(lib_id, None)
            for agent in members:
                manager._memory.remove_agent_derived_state(agent.agent_id)
                agent.lifecycle_state = "deleted"
                agent.llm_client = None
                agent.messages.clear()
                agent.message_history.clear()
                agent.agent_inbox.clear()
                agent._history_seen_ids.clear()
                agent._private_doc_library_id = None
                agent._manager = None
            team.members.clear()
            team.tools.clear()
            team.doc_library = None
            team.manager = None
            await asyncio.to_thread(self._discard_supervisory_trash, moved)
            manager._emit_callback(
                "on_system_event",
                "supervisory_team_dissolved",
                {"team_id": team.team_id, "auditor_agent_ids": sorted(member_ids)},
            )
            if cancelled:
                raise asyncio.CancelledError()

    @staticmethod
    def _discard_supervisory_trash(moved: list[tuple[str, str]]) -> None:
        for _original, trash in moved:
            shutil.rmtree(trash, ignore_errors=True)
