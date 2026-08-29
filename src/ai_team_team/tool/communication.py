"""Autonomous AgentTeam communication tools."""

import json
from typing import Any, Dict

from .context import _resolve_communication_context
from .contract import Tool


def build_communication_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def send_peer_message(team_id: str, message: str) -> str:
        """Sends a message through the ATT-configured communication regime."""
        try:
            actual_team, actual_agent = _resolve_communication_context(
                att_manager
            )
        except RuntimeError as exc:
            return json.dumps(
                {"status": "NO_AGREEMENT", "reason": str(exc)},
                sort_keys=True,
            )
        if team_id not in att_manager.teams:
            return json.dumps(
                {"status": "NO_AGREEMENT", "reason": f"Unknown AgentTeam {team_id!r}."}
            )
        target = att_manager.teams[team_id]
        result = await att_manager.broker.send_peer_message(
            actual_team,
            target,
            actual_agent.agent_id,
            message,
            invocation_id=att_manager._active_tool_invocation_id.get(),
        )
        return result.model_dump_json()

    async def request_peer_communication(
        team_id: str, rationale: str
    ) -> str:
        """Requests a persistent channel under ATT communication policy."""
        try:
            actual_team, actual_agent = _resolve_communication_context(
                att_manager
            )
        except RuntimeError as exc:
            return json.dumps(
                {"status": "DENIED", "reason": str(exc)}, sort_keys=True
            )
        if team_id not in att_manager.teams:
            return json.dumps(
                {"status": "DENIED", "reason": f"Unknown AgentTeam {team_id!r}."}
            )
        result = await att_manager.broker.request_peer_communication(
            actual_team,
            att_manager.teams[team_id],
            actual_agent.agent_id,
            rationale,
        )
        return result.model_dump_json()

    async def revoke_peer_agreement(
        agreement_id: str, reason: str
    ) -> str:
        """Revokes a channel when the current AgentTeam is an endpoint."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        result = await att_manager.broker.revoke_agreement(
            agreement_id, actual_team.team_id, reason
        )
        return result.model_dump_json()

    async def list_peer_requests(status: str = "pending") -> str:
        """Lists communication requests visible to the current AgentTeam."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        normalized = status.upper()
        rows = []
        for request in att_manager.broker.communication_requests.values():
            is_endpoint = actual_team.team_id in {
                request.sender_team_id,
                request.recipient_team_id,
            }
            is_approver = any(
                principal.kind == "agent_team"
                and principal.principal_id == actual_team.team_id
                for principal in request.approval_principals
            )
            if not (is_endpoint or is_approver):
                continue
            if normalized not in {"ALL", request.status.value}:
                continue
            rows.append(request.model_dump(mode="json"))
        return json.dumps(rows, sort_keys=True)

    async def list_peer_agreements(active_only: bool = True) -> str:
        """Lists agreements whose endpoint is the current AgentTeam."""
        try:
            actual_team, _ = _resolve_communication_context(att_manager)
        except RuntimeError as exc:
            return json.dumps(
                {"status": "FORBIDDEN", "reason": str(exc)},
                sort_keys=True,
            )
        rows = [
            agreement.model_dump(mode="json")
            for agreement in att_manager.broker.agreements.values()
            if actual_team.team_id
            in {agreement.source_team_id, agreement.target_team_id}
            and (agreement.active or not active_only)
        ]
        return json.dumps(rows, sort_keys=True)

    return {
        "send_peer_message": Tool(
            "send_peer_message",
            "Sends a message to a peer team's inbox using their Team ID. Arguments: team_id (str), message (str)",
            send_peer_message,
        ),
        "request_peer_communication": Tool(
            "request_peer_communication",
            "Requests a persistent peer communication channel. Arguments: team_id (str), rationale (str)",
            request_peer_communication,
        ),
        "revoke_peer_agreement": Tool(
            "revoke_peer_agreement",
            "Revokes an endpoint communication agreement. Arguments: agreement_id (str), reason (str)",
            revoke_peer_agreement,
        ),
        "list_peer_requests": Tool(
            "list_peer_requests",
            "Lists communication requests visible to the current AgentTeam. Arguments: status (str)",
            list_peer_requests,
        ),
        "list_peer_agreements": Tool(
            "list_peer_agreements",
            "Lists communication agreements visible to the current AgentTeam. Arguments: active_only (bool)",
            list_peer_agreements,
        ),
    }

