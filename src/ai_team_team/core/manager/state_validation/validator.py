"""Orchestration for complete persisted-state validation."""

from typing import Any, Dict

from ...config import ATTConfig
from .agents import validate_agents
from .libraries import validate_libraries
from .memory import validate_memory_state
from .payload import parse_state_validation_payload
from .permissions import validate_permissions_and_links
from .teams import validate_teams


class SnapshotValidationMixin:
    """Validate a snapshot before restore staging performs side effects."""

    def _validate_state_snapshot(self, state: Dict[str, Any]) -> ATTConfig:
        manager = self.manager
        payload = parse_state_validation_payload(state)
        configs = state["configs"]
        agent_ids, active_agent_ids, root_id = validate_agents(manager, payload, configs)
        team_ids = validate_teams(payload, agent_ids, active_agent_ids)
        library_ids, library_kinds, files_by_library = validate_libraries(
            manager, payload, agent_ids, team_ids
        )
        validate_permissions_and_links(
            manager,
            state,
            payload.permissions,
            library_ids,
            library_kinds,
            files_by_library,
            team_ids,
        )
        validate_memory_state(payload, agent_ids, team_ids)
        manager._validate_communication_state(
            payload.communication_requests,
            payload.communication_approvals,
            payload.communication_ballots,
            payload.communication_agreements,
            payload.peer_messages,
            team_ids,
            agent_ids,
            root_id,
            {row["team_id"]: row.get("inbox", []) for row in payload.teams},
        )
        return payload.config
