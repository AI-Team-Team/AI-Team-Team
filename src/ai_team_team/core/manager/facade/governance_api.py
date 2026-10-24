"""Personal email and explicit governance choices for continuing Agents."""

from typing import Any, Optional

from ...agent import Agent
from ...governance import GovernanceSubmissionResult
from ...response import InteractionResult
from ...team import AgentTeam


class GovernanceAPI:
    def open_agent_mail(self, message_id: str, *, actor: Agent) -> dict[str, Any]:
        return self._inbox.open(actor, message_id)

    async def submit_governance_choice(
        self, case_id: str, choice: dict[str, Any], *, actor: Agent
    ) -> GovernanceSubmissionResult:
        return await self._governance.submit(actor, case_id, choice)

    def list_governance_requests(
        self, *, actor: Agent, pending_only: bool = True
    ) -> list[dict[str, Any]]:
        if self._agents_by_id.get(actor.agent_id) is not actor or actor.lifecycle_state != "active":
            raise PermissionError("Governance requests require an active registered Agent.")
        return [
            self._governance.inspect(actor, item.case_id)
            for item in self._governance.cases.values()
            if actor.agent_id in item.voter_agent_ids
            and (not pending_only or self._governance.is_outstanding(actor.agent_id, item.case_id))
        ]

    async def execute_agent_interaction(
        self, agent: Agent, prompt: str, *, team: Optional[AgentTeam] = None
    ) -> InteractionResult:
        """Observe an answer from the common personal runtime without ending activity."""
        from ...activity.contracts import AgentTeamScope, PersonalScope
        if team is not None:
            if self.teams.get(team.team_id) is not team or agent not in team.members:
                raise PermissionError("The interaction's AgentTeam must contain this Agent.")
        return await self._activity.interact(agent, prompt,
            scope=AgentTeamScope(team_id=team.team_id) if team is not None else PersonalScope())
