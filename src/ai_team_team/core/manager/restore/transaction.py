"""State restore workflow for RestoreTransactionMixin."""

import asyncio
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple


from ...agent import Agent
from ...config import ATTConfig
from ...exceptions import StateRestoreError


class RestoreTransactionMixin:
    async def _apply_state_snapshot(self, state: Dict[str, Any]) -> None:
        """Stages, validates, and atomically publishes a restored state."""
        manager = self.manager
        from ..facade import ATTManager

        if manager._starting_invocations or manager._active_invocations:
            raise StateRestoreError(
                "Cannot restore state while agent invocations are active or starting."
            )
        if any(team.is_running for team in manager.teams.values()):
            raise StateRestoreError("Cannot restore state while a team discussion is active.")
        if any(agent.lock.locked() for agent in manager._agents_by_id.values()):
            raise StateRestoreError("Cannot restore state while an agent invocation is active.")
        if manager.token_budget.has_active_reservations():
            raise StateRestoreError(
                "Cannot restore state while model token reservations are active."
            )
        try:
            target_config = manager._validate_state_snapshot(state)
        except StateRestoreError:
            raise
        except Exception as exc:
            raise StateRestoreError(f"Invalid persisted state: {exc}") from exc
        workspace = os.path.realpath(os.path.abspath(target_config.workspace_root))
        managed_root = os.path.join(workspace, ".att_doc_libs")
        if os.path.lexists(managed_root) and os.path.islink(managed_root):
            raise StateRestoreError("The managed DocLib root cannot be a symbolic link.")
        os.makedirs(managed_root, exist_ok=True)
        staging_workspace = tempfile.mkdtemp(prefix=".att-restore-", dir=managed_root)
        staged_state = json.loads(json.dumps(state))
        staged_config_data = json.loads(staged_state["configs"]["att_config"])
        staged_config_data["workspace_root"] = staging_workspace
        staged_state["configs"]["att_config"] = json.dumps(staged_config_data)

        staged = ATTManager(
            Agent(
                "__restore_staging_root__",
                "Restore staging root",
                llm_client=manager.root_ai.llm_client,
            ),
            ATTConfig(workspace_root=staging_workspace),
            _restore_mode=True,
        )
        staged.llm_clients = dict(manager.llm_clients)
        staged.generator_handler = manager.generator_handler
        staged.global_tools = dict(manager.global_tools)
        published: List[Tuple[str, Optional[str]]] = []
        staged_closed = False
        try:
            await staged._apply_state_snapshot_unvalidated(staged_state)
            await staged._persistence.close()
            staged_closed = True
            staged.config = target_config
            staged.library_links = manager._normalized_library_links(state.get("links", {}))

            from ai_team_team.tool import get_default_tools

            for library in staged.libraries.values():
                library._on_change = manager._on_library_change
            for team in staged.teams.values():
                team.manager = manager
                team.invalidate_depth_cache(recursive=False)
                team.tools = get_default_tools(manager.tools_context, team)
                team.tools.update(manager.global_tools)
            for team in staged.teams.values():
                _ = team.depth

            published = manager._publish_staged_libraries(
                staged.libraries,
                managed_root,
            )
            old_state = {
                "config": manager.config,
                "root_ai": manager.root_ai,
                "agents": manager.agents,
                "agents_by_id": manager._agents_by_id,
                "teams": manager.teams,
                "libraries": manager.libraries,
                "library_permissions": manager.library_permissions,
                "library_links": manager.library_links,
                "library_files": manager._library_files,
                "team_parent_map": manager._team_parent_map,
                "model_configs": manager.model_configs,
                "presets": manager.presets,
                "model_token_usage": manager.model_token_usage,
                "communication_requests": manager.broker.communication_requests,
                "communication_approvals": manager.broker.communication_approvals,
                "communication_ballots": manager.broker.ballots,
                "communication_agreements": manager.broker.agreements,
                "peer_messages": manager.broker.peer_messages,
            }
            try:
                manager.config = target_config
                manager.root_ai = staged.root_ai
                manager.agents = staged.agents
                manager._agents_by_id = staged._agents_by_id
                manager.teams = staged.teams
                manager.libraries = staged.libraries
                manager.library_permissions = staged.library_permissions
                manager.library_links = staged.library_links
                manager._library_files = staged._library_files
                manager._team_parent_map = staged._team_parent_map
                manager.model_configs = staged.model_configs
                manager.presets = staged.presets
                manager.model_token_usage = staged.model_token_usage
                manager.broker.restore(
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.communication_requests.values()
                    ),
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.communication_approvals.values()
                    ),
                    (
                        item.model_dump(mode="json")
                        for values in staged.broker.ballots.values()
                        for item in values
                    ),
                    (item.model_dump(mode="json") for item in staged.broker.agreements.values()),
                    (item.model_dump(mode="json") for item in staged.broker.peer_messages.values()),
                )
                manager.supervisor.root_ai = manager.root_ai
                manager.tools_context["att_manager"] = manager
                manager.token_budget.reset_reservations()
            except Exception:
                manager.config = old_state["config"]
                manager.root_ai = old_state["root_ai"]
                manager.agents = old_state["agents"]
                manager._agents_by_id = old_state["agents_by_id"]
                manager.teams = old_state["teams"]
                manager.libraries = old_state["libraries"]
                manager.library_permissions = old_state["library_permissions"]
                manager.library_links = old_state["library_links"]
                manager._library_files = old_state["library_files"]
                manager._team_parent_map = old_state["team_parent_map"]
                manager.model_configs = old_state["model_configs"]
                manager.presets = old_state["presets"]
                manager.model_token_usage = old_state["model_token_usage"]
                manager.broker.communication_requests = old_state["communication_requests"]
                manager.broker.communication_approvals = old_state["communication_approvals"]
                manager.broker.ballots = old_state["communication_ballots"]
                manager.broker.agreements = old_state["communication_agreements"]
                manager.broker.peer_messages = old_state["peer_messages"]
                manager.supervisor.root_ai = manager.root_ai
                manager._rollback_published_libraries(published)
                published = []
                raise
            manager._discard_library_backups(published)
            published = []
        except StateRestoreError:
            if published:
                manager._rollback_published_libraries(published)
            raise
        except Exception as exc:
            if published:
                manager._rollback_published_libraries(published)
            raise StateRestoreError(f"State restoration failed before commit: {exc}") from exc
        finally:
            if not staged_closed:
                await asyncio.shield(staged._persistence.close())
            shutil.rmtree(staging_workspace, ignore_errors=True)
