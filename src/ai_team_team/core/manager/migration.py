"""Topology migration authorization and atomic commit workflow."""

from typing import TYPE_CHECKING, Tuple

from ..team import AgentTeam

if TYPE_CHECKING:
    from .facade import ATTManager


class MigrationService:
    """Owns migration authorization, revalidation, and topology commit."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    async def negotiate_and_execute_migration(
        self, team: AgentTeam, target_parent: AgentTeam, rationale: str
    ) -> Tuple[bool, str]:
        """Arbitrates the migration of an AgentTeam using the critic LLM client, updates structure, and broadcasts alerts."""
        manager = self.manager
        from ..policies import (
            migration_approval_principals,
            resolve_migration_policy,
        )

        limit = manager.config.max_migrations_per_team_discussion
        policy_name = getattr(manager.config, "migration_policy", "ancestor_approval")
        policy = resolve_migration_policy(policy_name)
        with manager._topology_lock:
            if manager.teams.get(team.team_id) is not team:
                return False, "Rejected: Migrating AgentTeam is not registered."
            if manager.teams.get(target_parent.team_id) is not target_parent:
                return False, "Rejected: Target parent AgentTeam is not registered."
            current_count = getattr(team, "migration_count", 0)
            if current_count >= limit:
                return (
                    False,
                    f"Rejected: Cannot request migration. Maximum migrations per discussion session ({limit}) reached.",
                )
            initial_parent = team.parent_team
            if initial_parent is not None and team not in initial_parent.child_teams:
                return False, "Rejected: Current parent/child topology is inconsistent."
            cursor = target_parent
            while cursor is not None:
                if cursor is team:
                    return (
                        False,
                        "Rejected: Target parent is a descendant of the migrating AgentTeam.",
                    )
                cursor = cursor.parent_team
            approved_principal_keys = tuple(
                principal.key
                for principal in migration_approval_principals(
                    policy_name, team, target_parent, manager
                )
            )
            current_parent_id = initial_parent.team_id if initial_parent else "Root AI"

        try:
            approved, reason = await policy.authorize_migration(
                team, target_parent, manager, rationale
            )

            if approved:
                with manager._topology_lock:
                    if manager.teams.get(team.team_id) is not team:
                        return False, (
                            "Rejected: Migrating AgentTeam was unregistered "
                            "while authorization was pending."
                        )
                    if manager.teams.get(target_parent.team_id) is not target_parent:
                        return False, (
                            "Rejected: Target parent AgentTeam was unregistered "
                            "while authorization was pending."
                        )
                    current_parent = team.parent_team
                    current_count = team.migration_count
                    if current_parent is not initial_parent:
                        return False, (
                            "Rejected: Current parent changed while authorization was pending."
                        )
                    if current_parent is not None and team not in current_parent.child_teams:
                        return False, (
                            "Rejected: Current parent/child topology became "
                            "inconsistent while authorization was pending."
                        )
                    if current_count >= limit:
                        return False, (
                            "Rejected: Migration limit was reached while authorization was pending."
                        )

                    cursor = target_parent
                    while cursor is not None:
                        if cursor is team:
                            return False, (
                                "Rejected: Target parent became a descendant "
                                "while authorization was pending."
                            )
                        cursor = cursor.parent_team

                    current_principal_keys = tuple(
                        principal.key
                        for principal in migration_approval_principals(
                            policy_name, team, target_parent, manager
                        )
                    )
                    if current_principal_keys != approved_principal_keys:
                        return False, (
                            "Rejected: The migration approval path changed "
                            "while authorization was pending."
                        )

                    if current_parent and team in current_parent.child_teams:
                        current_parent.child_teams.remove(team)
                    target_parent.add_child_team(team)
                    team._parent_team = target_parent
                    manager._team_parent_map[team.team_id] = target_parent.team_id
                    team.migration_count = current_count + 1
                    team.invalidate_depth_cache(recursive=True)

                # 2. Dispatch notifications
                if current_parent:
                    current_parent.receive_message(
                        {
                            "from": "System/Migration",
                            "type": "migration_alert",
                            "reason": f"Child team '{team.team_id}' has migrated to parent '{target_parent.team_id}'. Rationale: {rationale}",
                        }
                    )
                target_parent.receive_message(
                    {
                        "from": "System/Migration",
                        "type": "migration_alert",
                        "reason": f"Team '{team.team_id}' has joined as your child. Rationale: {rationale}",
                    }
                )
                team.receive_message(
                    {
                        "from": "System/Migration",
                        "type": "migration_alert",
                        "reason": f"Your team has successfully migrated to parent '{target_parent.team_id}'. Arbiter Reason: {reason}",
                    }
                )

                # 3. Trigger callback
                manager._emit_callback(
                    "on_team_migration",
                    team.team_id,
                    current_parent_id if current_parent else None,
                    target_parent.team_id,
                )

                manager.logger.info(
                    f"Migration of team {team.team_id} to parent {target_parent.team_id} approved. Reason: {reason}"
                )
                affected_team_ids = {
                    team.team_id,
                    target_parent.team_id,
                }
                if current_parent:
                    affected_team_ids.add(current_parent.team_id)

                def collect_descendants(node: AgentTeam) -> None:
                    for child in node.child_teams:
                        affected_team_ids.add(child.team_id)
                        collect_descendants(child)

                collect_descendants(team)
                manager._auto_save(teams=affected_team_ids)
                return True, f"Approved: {reason}"
            else:
                manager.logger.info(
                    f"Migration of team {team.team_id} to parent {target_parent.team_id} rejected. Reason: {reason}"
                )
                return False, f"Rejected: {reason}"

        except Exception as e:
            manager.logger.error(f"Migration arbitration error: {e}")
            return False, f"Arbitration error: {e}"
