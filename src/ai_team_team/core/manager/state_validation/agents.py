"""Agent reference and runtime-binding validation for restored state."""

import json
import uuid
from typing import Any, Dict, Set, Tuple

from ...exceptions import StateRestoreError
from .payload import StateValidationPayload


def validate_agents(
    manager: Any,
    payload: StateValidationPayload,
    configs: Dict[str, Any],
) -> Tuple[Set[str], Set[str], str]:
    """Validate agent identities, lifecycle state, and model bindings."""
    agent_ids = [row.get("agent_id") for row in payload.agents]
    agent_names = [row.get("name") for row in payload.agents]
    if None in agent_ids or len(agent_ids) != len(set(agent_ids)):
        raise StateRestoreError("Agent IDs are missing or duplicated.")
    for agent_id in agent_ids:
        try:
            if str(uuid.UUID(agent_id)) != agent_id:
                raise ValueError
        except (ValueError, AttributeError, TypeError) as exc:
            raise StateRestoreError(f"Agent ID {agent_id!r} is not a canonical UUID.") from exc
    if None in agent_names or len(agent_names) != len(set(agent_names)):
        raise StateRestoreError("Agent names are missing or duplicated.")

    agent_id_set = set(agent_ids)
    active_agent_ids = {
        row["agent_id"] for row in payload.agents if row.get("lifecycle_state") == "active"
    }
    for row in payload.agents:
        if row.get("lifecycle_state") not in {
            "active",
            "retained",
            "archived",
        }:
            raise StateRestoreError(
                f"Agent {row.get('agent_id')!r} has an invalid lifecycle state."
            )

    root_id = configs.get("root_ai_id")
    if root_id not in active_agent_ids:
        raise StateRestoreError(f"Persisted root agent {root_id!r} was not found or is inactive.")
    if not isinstance(payload.model_configs, dict) or not isinstance(payload.presets, dict):
        raise StateRestoreError("Persisted model configurations and presets must be objects.")
    if not isinstance(payload.model_token_usage, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in payload.model_token_usage.values()
    ):
        raise StateRestoreError("Persisted model token usage must contain non-negative integers.")
    if any(
        row.get("model_alias") is None
        for row in payload.agents
        if row.get("lifecycle_state") == "active"
    ):
        raise StateRestoreError(
            "Every active persisted agent must reference an explicit model alias."
        )

    missing_aliases = sorted(
        {
            row.get("model_alias")
            for row in payload.agents
            if row.get("lifecycle_state") == "active"
            if row.get("model_alias") != "default"
            and (
                row.get("model_alias") not in manager.llm_clients
                and not (
                    manager.generator_handler and row.get("model_alias") in payload.model_configs
                )
            )
        }
    )
    if missing_aliases:
        raise StateRestoreError(
            "Missing runtime bindings for model aliases: " + ", ".join(missing_aliases)
        )
    has_default_binding = bool("default" in manager.llm_clients or manager.generator_handler)
    if (
        any(
            row.get("model_alias") == "default"
            for row in payload.agents
            if row.get("lifecycle_state") == "active"
        )
        and not has_default_binding
    ):
        raise StateRestoreError("No runtime binding is available for the default model alias.")
    for row in payload.agents:
        if row.get("last_context"):
            try:
                json.loads(row["last_context"])
            except Exception as exc:
                raise StateRestoreError(
                    f"Agent {row['name']!r} has invalid last_context JSON."
                ) from exc

    return agent_id_set, active_agent_ids, root_id
