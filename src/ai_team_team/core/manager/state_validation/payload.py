"""Parsing for persisted manager-state payloads."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from ...config import ATTConfig
from ...exceptions import StateRestoreError


@dataclass(frozen=True)
class StateValidationPayload:
    """The structurally decoded portion of a persisted state snapshot."""

    config: ATTConfig
    model_configs: Dict[str, Any]
    presets: Dict[str, Any]
    model_token_usage: Dict[str, Any]
    agents: List[Dict[str, Any]]
    teams: List[Dict[str, Any]]
    libraries: List[Dict[str, Any]]
    permissions: Dict[str, Any]
    communication_requests: List[Dict[str, Any]]
    communication_approvals: List[Dict[str, Any]]
    communication_ballots: List[Dict[str, Any]]
    communication_agreements: List[Dict[str, Any]]
    peer_messages: List[Dict[str, Any]]


def parse_state_validation_payload(
    state: Dict[str, Any],
) -> StateValidationPayload:
    """Decode the persisted JSON configuration and required entity collections."""
    try:
        configs = state["configs"]
        return StateValidationPayload(
            config=ATTConfig(**json.loads(configs["att_config"])),
            model_configs=json.loads(configs.get("model_configs", "{}")),
            presets=json.loads(configs.get("presets", "{}")),
            model_token_usage=json.loads(configs.get("model_token_usage", "{}")),
            agents=state["agents"],
            teams=state["teams"],
            libraries=state["libraries"],
            permissions=state["permissions"],
            communication_requests=state["communication_requests"],
            communication_approvals=state["communication_approvals"],
            communication_ballots=state["communication_ballots"],
            communication_agreements=state["communication_agreements"],
            peer_messages=state["peer_messages"],
        )
    except Exception as exc:
        raise StateRestoreError(f"Invalid persisted state structure: {exc}") from exc
