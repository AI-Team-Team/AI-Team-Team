"""Operation-owned creation undo, never a snapshot of another transaction."""

import shutil


class TeamCreationPublication:
    def __init__(self, manager, stage):
        self.manager = manager
        self.stage = stage
        self.previous_agent_fields = {
            agent.agent_id: (agent.private_doc_library_id, getattr(agent, "_manager", None))
            for agent in stage["new_agents"]
        }
        self.rolled_back = False

    def validate(self):
        """Repeat live authority checks at the final receipt admission boundary."""
        self.manager._team_creation.validate_published_creation(self.stage)

    def rollback(self):
        """Withdraw only exact objects and initial relationship facts owned here."""
        if self.rolled_back:
            return
        manager, stage = self.manager, self.stage
        team = stage["team"]
        with manager._resources.settlement(), manager._resources.topology_mutation(), manager._snapshot_lock:
            if manager.teams.get(team.team_id) is team:
                manager.teams.pop(team.team_id)
                manager._team_parent_map.pop(team.team_id, None)
                parent = stage["parent"]
                if parent is not None and hasattr(parent, "child_teams"):
                    parent.child_teams[:] = [child for child in parent.child_teams if child is not team]
            manager._records.discard_initial_team(team.team_id)
            for member in team.members:
                initial_id = f"INITIAL-{team.team_id}-{member.agent_id}"
                with member.inbox_lock:
                    member.agent_inbox[:] = [mail for mail in member.agent_inbox if mail["message_id"] != initial_id]
                manager._inbox.finish_staged((initial_id,))
            for agent in stage["new_agents"]:
                if manager._agents_by_id.get(agent.agent_id) is agent:
                    manager._agents_by_id.pop(agent.agent_id)
                if manager.agents.get(agent.name) is agent:
                    manager.agents.pop(agent.name)
                agent._private_doc_library_id, agent._manager = self.previous_agent_fields[agent.agent_id]
            manager._agent_registry.refresh_names()
            for lib_id, library in stage["libraries"].items():
                if manager.libraries.get(lib_id) is library:
                    manager.libraries.pop(lib_id)
                    manager._library_files.pop(lib_id, None)
                    manager.library_permissions.pop(lib_id, None)
                    manager.library_links.pop(lib_id, None)
                    shutil.rmtree(library.root_dir, ignore_errors=True)
            self.rolled_back = True
