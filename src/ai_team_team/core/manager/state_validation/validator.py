"""Orchestration for complete persisted-state validation."""

from typing import Any, Dict

from ...config import ATTConfig
from ...exceptions import StateRestoreError
from .activity import validate_activity_contexts
from .agents import validate_agents
from .libraries import validate_libraries
from .memory import validate_memory_state
from .formations import validate_formations
from .governance import validate_governance
from .payload import parse_state_validation_payload
from .permissions import validate_permissions_and_links
from .teams import validate_teams
from ai_team_team.database.persistence.store.detached_validation import validate_detached_records


class SnapshotValidationMixin:
    """Validate a snapshot before restore staging performs side effects."""

    def _validate_state_snapshot(self, state: Dict[str, Any]) -> ATTConfig:
        manager = self.manager
        payload = parse_state_validation_payload(state)
        configs = state["configs"]
        agent_ids, active_agent_ids, root_id = validate_agents(manager, payload, configs)
        team_ids = validate_teams(payload, agent_ids, active_agent_ids)
        validate_formations(
            manager,
            payload,
            agent_ids,
            active_agent_ids,
            team_ids,
        )
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
        validate_governance(payload, agent_ids, team_ids, root_id)
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
            inactive_team_ids={row["team_id"] for row in payload.teams if row.get("lifecycle_state", "active") != "active"},
        )
        validate_detached_records(state)
        validate_activity_contexts(payload, state.get("records", ()))
        index = {record.identity: record for record in state.get("records", ())}
        for draft in payload.formation_drafts:
            invocation_id = draft.get("initiator_invocation_id")
            if invocation_id is not None:
                source = index.get(("activity_invocations", (invocation_id,)))
                if source is None or source.values["agent_id"] != draft["initiator_agent_id"]:
                    raise StateRestoreError("A formation candidate has a missing or cross-owner invocation source.")
                if source.values["started_at"] > draft["created_at"]:
                    raise StateRestoreError("A formation candidate predates its invocation source.")
            message_id = draft.get("source_message_id")
            if message_id is not None:
                source = index.get(("chat_messages", (message_id,)))
                if source is None or source.values["author_agent_id"] != draft["initiator_agent_id"]:
                    raise StateRestoreError("A formation candidate has a missing or cross-owner authored message source.")
                if source.values["created_at"] > draft["created_at"]:
                    raise StateRestoreError("A formation candidate predates its authored message source.")
        for agent in payload.agents:
            for message in agent.get("messages", ()):
                for field, table in (("invocation_id", "activity_invocations"), ("source_execution_id", "executions")):
                    identifier = message.get(field)
                    if identifier is not None:
                        record = index.get((table, (identifier,)))
                        if record is None or record.values["agent_id"] != agent["agent_id"]:
                            raise StateRestoreError("A personal context has a missing or cross-owner source reference.")
                if message.get("source_chat_message_id") is not None and not any(
                        record.table_name == "chat_personal_views" and record.values["agent_id"] == agent["agent_id"]
                        and record.values["message_id"] == message["source_chat_message_id"] for record in index.values()):
                    raise StateRestoreError("A personal context has no authorized chat source view.")
        return payload.config
