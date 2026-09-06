"""Manager configuration, Agent, AgentTeam, inbox, and proposal writes."""

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete

from ai_team_team.database.models import (
    AgentMessageModel,
    AgentModel,
    ManagerConfigModel,
    TeamInboxModel,
    TeamModel,
    TeamProposalModel,
    team_members,
)


class CoreStateWriteMixin:
    @staticmethod
    def _write_configs(session: Any, configs: Optional[Dict[str, str]]) -> None:
        if configs is None:
            return
        for key, value in configs.items():
            session.merge(ManagerConfigModel(config_key=key, config_value=value))

    @staticmethod
    def _write_agents(session: Any, agents: Iterable[Dict[str, Any]]) -> None:
        for agent in agents:
            session.merge(
                AgentModel(
                    agent_id=agent["agent_id"],
                    name=agent["name"],
                    role=agent["role"],
                    role_description=agent["role_description"],
                    system_instructions=agent["system_instructions"],
                    model_alias=agent["model_alias"],
                    last_context=agent["last_context"],
                    lifecycle_state=agent["lifecycle_state"],
                )
            )
            session.query(AgentMessageModel).filter_by(agent_id=agent["agent_id"]).delete(
                synchronize_session=False
            )
            for index, message in enumerate(agent["messages"]):
                session.add(
                    AgentMessageModel(
                        agent_id=agent["agent_id"],
                        role=message.get("role", "user"),
                        content=message.get("content"),
                        tool_calls=message.get("tool_calls"),
                        tool_call_id=message.get("tool_call_id"),
                        name=message.get("name"),
                        team_id=message.get("team_id"),
                        discussion_id=message.get("discussion_id"),
                        created_at=agent["message_timestamp"] + index * 0.001,
                    )
                )

    @classmethod
    def _write_agent_dependencies(
        cls,
        session: Any,
        agents: Iterable[Dict[str, Any]],
    ) -> None:
        """Inserts missing FK targets without rewriting existing Agent state."""
        missing = [
            agent
            for agent in agents
            if session.get(AgentModel, agent["agent_id"]) is None
        ]
        unresolved = [agent["name"] for agent in missing if agent.get("_dependency_error")]
        if unresolved:
            raise ValueError(
                "Cannot persist agents whose LLM clients have no stable, "
                "unique registered alias: " + ", ".join(unresolved)
            )
        cls._write_agents(session, missing)

    @staticmethod
    def _write_teams(session: Any, teams: Iterable[Dict[str, Any]]) -> None:
        teams = list(teams)
        for team in teams:
            session.merge(
                TeamModel(
                    team_id=team["team_id"],
                    preset_name=team["preset_name"],
                    team_purpose=team["team_purpose"],
                    team_progress=team["team_progress"],
                    depth=team["depth"],
                    chapter_num=team["chapter_num"],
                    parent_team_id=None,
                    migration_count=team["migration_count"],
                    creator_agent_id=(
                        team["creator_id"] if team["creator_type"] == "agent" else None
                    ),
                    creator_team_id=(
                        team["creator_id"] if team["creator_type"] == "team" else None
                    ),
                    status_map=team["status_map"],
                    system_instructions=team["system_instructions"],
                )
            )
        session.flush()
        for team in teams:
            session.query(TeamModel).filter_by(team_id=team["team_id"]).update(
                {"parent_team_id": team["parent_team_id"]},
                synchronize_session=False,
            )
        session.flush()
        for team in teams:
            session.execute(delete(team_members).where(team_members.c.team_id == team["team_id"]))
            for member_id in team["members"]:
                session.execute(
                    team_members.insert().values(team_id=team["team_id"], agent_id=member_id)
                )

    @staticmethod
    def _write_inboxes(session: Any, inboxes: Dict[str, Dict[str, Any]]) -> None:
        for team_id, inbox in inboxes.items():
            session.query(TeamInboxModel).filter_by(team_id=team_id).delete(
                synchronize_session=False
            )
            for index, message in enumerate(inbox["messages"]):
                session.add(
                    TeamInboxModel(
                        team_id=team_id,
                        sender=message.get("from", "Unknown"),
                        msg_type=message.get("type", "Unknown"),
                        payload=json.dumps(message),
                        created_at=(inbox["message_timestamp"] + index * 0.001),
                    )
                )

    @staticmethod
    def _write_proposals(session: Any, proposals: Dict[str, List[Dict[str, Any]]]) -> None:
        for team_id, team_proposals in proposals.items():
            session.query(TeamProposalModel).filter_by(team_id=team_id).delete(
                synchronize_session=False
            )
            for proposal in team_proposals:
                session.add(
                    TeamProposalModel(
                        proposal_id=proposal["proposal_id"],
                        team_id=team_id,
                        action=proposal.get("action"),
                        target=proposal.get("target"),
                        initiator_type=proposal.get("initiator_type"),
                        initiator_name=proposal.get("initiator_name"),
                        initiator_agent_id=proposal.get("initiator_agent_id"),
                        rationale=proposal.get("rationale"),
                        proposed_details=json.dumps(proposal.get("proposed_details", {})),
                        votes=json.dumps(proposal.get("votes", {})),
                        status=proposal.get("status"),
                    )
                )
