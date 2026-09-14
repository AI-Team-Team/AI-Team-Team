"""Formation proposal validation and creation."""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ...agent import Agent
from ...formation import (
    LateJoinPolicy,
    TeamFormationInvitation,
    TeamFormationRequest,
    UnanimousAcceptanceAction,
)
from ...team import AgentTeam


class FormationProposalMixin:
    @staticmethod
    def _proposal_fingerprint(payload: Dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _resolve_initiator(
        self,
        creator: Any,
        initiating_agent: Optional[Agent],
    ) -> Agent:
        manager = self.manager
        active_agent = manager._active_tool_agent.get()
        initiator = initiating_agent or active_agent
        if isinstance(creator, Agent):
            if initiator is None:
                initiator = creator
            if initiator is not creator:
                raise ValueError("An Agent creator must also be the formation initiator.")
        elif isinstance(creator, AgentTeam):
            if initiator is None:
                raise ValueError(
                    "Formation under an AgentTeam requires an explicit initiating_agent."
                )
            if all(member.agent_id != initiator.agent_id for member in creator.members):
                raise ValueError(
                    "The formation initiator must be an active member of the creator AgentTeam."
                )
        else:
            raise TypeError("creator must be an Agent or AgentTeam.")
        if (
            manager._agents_by_id.get(initiator.agent_id) is not initiator
            or manager.agents.get(initiator.name) is not initiator
            or initiator.lifecycle_state != "active"
        ):
            raise ValueError("The formation initiator must be actively registered.")
        return initiator

    def _resolve_parent(self, creator: Any, initiator: Agent) -> Optional[AgentTeam]:
        manager = self.manager
        if isinstance(creator, AgentTeam):
            return creator
        active_team = manager._active_team.get()
        if (
            active_team is not None
            and manager.teams.get(active_team.team_id) is active_team
            and any(member.agent_id == initiator.agent_id for member in active_team.members)
        ):
            return active_team
        return manager.get_agent_team(creator)

    def propose_team_formation(
        self,
        *,
        creator: Any,
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        preset_name: str = "custom",
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_members: Optional[List[Agent]] = None,
        existing_member_ids: Optional[List[str]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None,
        initiating_agent: Optional[Agent] = None,
        initiator_joins: bool = False,
        unanimous_acceptance_action: str = "require_confirmation",
        late_join_policy: str = "disabled",
        task: Optional[str] = None,
    ) -> TeamFormationRequest:
        manager = self.manager
        if manager._closing:
            raise RuntimeError("ATTManager is closing and rejects new formations.")
        if manager._restore_in_progress:
            raise RuntimeError("ATTManager is restoring state and rejects new formations.")
        if type(initiator_joins) is not bool:
            raise TypeError("initiator_joins must be a boolean.")
        initiator = self._resolve_initiator(creator, initiating_agent)
        invitees = manager._resolve_existing_team_members(
            existing_members,
            existing_member_ids,
        )
        if not invitees and not initiator_joins:
            raise ValueError(
                "A formation request requires at least one existing invitee or initiator_joins=True."
            )
        if any(agent.agent_id == initiator.agent_id for agent in invitees):
            raise ValueError(
                "The initiator cannot invite itself; use initiator_joins=True instead."
            )
        try:
            completion = UnanimousAcceptanceAction(unanimous_acceptance_action)
            late_join = LateJoinPolicy(late_join_policy)
        except ValueError as exc:
            raise ValueError(
                "Invalid formation completion or late-join policy."
            ) from exc
        proposed_existing = list(invitees)
        if initiator_joins:
            proposed_existing.append(initiator)
        manager._validate_team_creation_inputs(
            creator=creator,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=proposed_existing,
            existing_member_ids=None,
            initial_docs=initial_docs,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            is_public_visible=is_public_visible,
        )
        parent = self._resolve_parent(creator, initiator)
        now = time.time()
        request_id = f"TFR-{uuid.uuid4().hex}"
        roles_payload = (
            [[name, role] for name, role in roles_and_presets]
            if roles_and_presets is not None
            else None
        )
        creator_kind = "agent_team" if isinstance(creator, AgentTeam) else "agent"
        creator_id = creator.team_id if isinstance(creator, AgentTeam) else creator.agent_id
        fingerprint_payload = {
            "creator_kind": creator_kind,
            "creator_id": creator_id,
            "parent_team_id": parent.team_id if parent else None,
            "task": task,
            "member_count": member_count,
            "roles_and_presets": roles_payload,
            "preset_name": preset_name,
            "system_instructions": system_instructions,
            "team_purpose": team_purpose,
            "roles_and_models": roles_and_models,
            "member_configs": member_configs,
            "invitee_agent_ids": [agent.agent_id for agent in invitees],
            "initial_docs": initial_docs,
            "is_public_visible": is_public_visible,
            "initiator_joins": initiator_joins,
            "unanimous_acceptance_action": completion.value,
            "late_join_policy": late_join.value,
            "proposal_revision": 1,
        }
        request = TeamFormationRequest(
            request_id=request_id,
            initiator_agent_id=initiator.agent_id,
            creator_kind=creator_kind,
            creator_id=creator_id,
            parent_team_id=parent.team_id if parent else None,
            task=task,
            member_count=member_count,
            roles_and_presets=roles_payload,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=(
                dict(roles_and_models) if roles_and_models is not None else None
            ),
            member_configs=(
                {name: dict(config) for name, config in member_configs.items()}
                if member_configs is not None
                else None
            ),
            invitee_agent_ids=[agent.agent_id for agent in invitees],
            initial_docs=(dict(initial_docs) if initial_docs is not None else None),
            is_public_visible=is_public_visible,
            initiator_joins=initiator_joins,
            unanimous_acceptance_action=completion,
            late_join_policy=late_join,
            proposal_fingerprint=self._proposal_fingerprint(fingerprint_payload),
            created_at=now,
            updated_at=now,
        )
        invitations = [
            TeamFormationInvitation(
                request_id=request_id,
                agent_id=agent.agent_id,
                proposal_revision=request.proposal_revision,
            )
            for agent in invitees
        ]
        inbox_ids = set()
        with self._state_lock:
            self.requests[request_id] = request
            for invitation in invitations:
                self.invitations[(request_id, invitation.agent_id)] = invitation
                self._notify_agent(
                    invitation.agent_id,
                    "team_formation_invitation",
                    {
                        "request_id": request_id,
                        "initiator_agent_id": initiator.agent_id,
                        "team_purpose": team_purpose,
                        "proposal_revision": request.proposal_revision,
                    },
                )
                inbox_ids.add(invitation.agent_id)
            self._notify_agent(
                initiator.agent_id,
                "team_formation_proposed",
                {
                    "request_id": request_id,
                    "invitee_count": len(invitations),
                    "team_purpose": team_purpose,
                },
            )
            inbox_ids.add(initiator.agent_id)
        manager._auto_save(
            configs=True,
            formation_requests={request_id},
            formation_invitations={request_id},
            agent_inboxes=inbox_ids,
        )
        manager._emit_callback(
            "on_system_event",
            "team_formation_proposed",
            {
                "request_id": request_id,
                "initiator_agent_id": initiator.agent_id,
                "invitee_count": len(invitations),
            },
        )
        return request
