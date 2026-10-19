"""Manager configuration, Agent, AgentTeam, inbox, and proposal writes."""

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select

from ai_team_team.database.models import (
    AgentMessageModel,
    ACTIVITY_TABLES,
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
            if key == "publication_generation":
                previous = session.get(ManagerConfigModel, key)
                if previous is not None and int(previous.config_value) > int(value):
                    continue
            session.merge(ManagerConfigModel(config_key=key, config_value=value))

    @staticmethod
    def _write_agents(session: Any, agents: Iterable[Dict[str, Any]]) -> None:
        for agent in agents:
            previous = session.get(AgentModel, agent["agent_id"])
            if previous is not None and previous.state_version > agent.get("state_version", 1):
                continue
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
                    state_version=agent.get("state_version", 1),
                    presentation_preferences=agent.get("presentation_preferences", {}),
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
                        invocation_id=message.get("invocation_id"),
                        source_chat_message_id=message.get("source_chat_message_id"),
                        source_execution_id=message.get("source_execution_id"),
                        source_metadata={key: value for key, value in message.items()
                                         if key not in {"role", "content", "tool_calls", "tool_call_id", "name", "team_id", "invocation_id", "source_chat_message_id", "source_execution_id"}},
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
    def _missing_team_dependencies(
        session: Any,
        teams: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Selects missing provenance teams without rewriting existing topology."""
        return [
            team for team in teams if session.get(TeamModel, team["team_id"]) is None
        ]

    @staticmethod
    def _write_teams(session: Any, teams: Iterable[Dict[str, Any]], records=()) -> None:
        # Team creators have immediate self-FKs, unlike the deferred parent pointers.
        pending = {team["team_id"]: team for team in teams}
        teams = []
        while pending:
            ready = [
                team
                for team in pending.values()
                if team["creator_type"] != "team" or team["creator_id"] not in pending
            ]
            if not ready:
                raise ValueError("Cannot persist cyclic AgentTeam creator dependencies.")
            for team in sorted(ready, key=lambda record: record["team_id"]):
                teams.append(team)
                del pending[team["team_id"]]
        accepted = []
        for team in teams:
            previous = session.get(TeamModel, team["team_id"])
            if previous is not None and previous.state_version > team.get("state_version", 1):
                continue
            accepted.append(team)
            session.merge(
                TeamModel(
                    team_id=team["team_id"],
                    team_kind=team["team_kind"],
                    preset_name=team["preset_name"],
                    team_purpose=team["team_purpose"],
                    team_progress=team["team_progress"],
                    chapter_num=team["chapter_num"],
                    parent_team_id=None,
                    state_version=team.get("state_version", 1),
                    parent_agent_id=team.get("parent_agent_id"),
                    lifecycle_state=team.get("lifecycle_state", "active"),
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
        teams = accepted
        session.flush()
        for team in teams:
            session.query(TeamModel).filter_by(team_id=team["team_id"]).update(
                {"parent_team_id": team["parent_team_id"]},
                synchronize_session=False,
            )
        session.flush()

    @staticmethod
    def _sync_current_memberships(session: Any, records, teams) -> None:
        """Derive the live projection from accepted intervals, never stale metadata.

        A later queued progress snapshot may legitimately contain an older
        runtime member list while the relationship receipt is settling. The
        interval records, with their independent versions, remain authoritative.
        """
        ordering = {team["team_id"]: team["members"] for team in teams}
        identifiers = set(ordering) | {row.values["team_id"] for row in records if row.table_name == "membership_intervals"}
        intervals = ACTIVITY_TABLES["membership_intervals"]
        events, streams = ACTIVITY_TABLES["chat_events"], ACTIVITY_TABLES["chat_streams"]
        for team_id in sorted(identifiers):
            current = dict(session.execute(select(intervals.c.agent_id, intervals.c.interval_id).where(
                intervals.c.team_id == team_id, intervals.c.leave_event_id.is_(None))).all())
            ordered = [owner for owner in ordering.get(team_id, ()) if owner in current]
            ordered.extend(sorted(current.keys() - set(ordered)))
            session.execute(delete(team_members).where(team_members.c.team_id == team_id))
            if ordered:
                session.execute(team_members.insert(), [dict(team_id=team_id, agent_id=owner,
                    interval_id=current[owner]) for owner in ordered])
            dissolved = session.execute(select(events.c.event_id).join(streams, events.c.stream_id == streams.c.stream_id).where(
                streams.c.team_id == team_id, events.c.event_kind == "dissolve")).first()
            if dissolved:
                session.query(TeamModel).filter_by(team_id=team_id).update({"lifecycle_state": "dissolved"}, synchronize_session=False)

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
