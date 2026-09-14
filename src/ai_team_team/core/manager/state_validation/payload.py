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
    agent_inboxes: Dict[str, List[Dict[str, Any]]]
    teams: List[Dict[str, Any]]
    formation_requests: List[Dict[str, Any]]
    formation_invitations: List[Dict[str, Any]]
    formation_revisions: List[Dict[str, Any]]
    formation_decisions: List[Dict[str, Any]]
    formation_drafts: List[Dict[str, Any]]
    libraries: List[Dict[str, Any]]
    permissions: Dict[str, Any]
    communication_requests: List[Dict[str, Any]]
    communication_approvals: List[Dict[str, Any]]
    communication_ballots: List[Dict[str, Any]]
    communication_agreements: List[Dict[str, Any]]
    peer_messages: List[Dict[str, Any]]
    memory_events: List[Dict[str, Any]]
    memory_segments: List[Dict[str, Any]]
    memory_cards: List[Dict[str, Any]]
    memory_references: List[Dict[str, Any]]


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
            agent_inboxes=state["agent_inboxes"],
            teams=state["teams"],
            formation_requests=state["formation_requests"],
            formation_invitations=state["formation_invitations"],
            formation_revisions=state["formation_revisions"],
            formation_decisions=state["formation_decisions"],
            formation_drafts=state["formation_drafts"],
            libraries=state["libraries"],
            permissions=state["permissions"],
            communication_requests=state["communication_requests"],
            communication_approvals=state["communication_approvals"],
            communication_ballots=state["communication_ballots"],
            communication_agreements=state["communication_agreements"],
            peer_messages=state["peer_messages"],
            memory_events=state["memory_events"],
            memory_segments=state["memory_segments"],
            memory_cards=state["memory_cards"],
            memory_references=state["memory_references"],
        )
    except Exception as exc:
        raise StateRestoreError(f"Invalid persisted state structure: {exc}") from exc
