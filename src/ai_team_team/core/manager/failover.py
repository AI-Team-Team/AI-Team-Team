"""Token-budget failover selection and client replacement."""

import asyncio
from typing import TYPE_CHECKING

from ..adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ..agent import Agent
from ..exceptions import TokenLimitExceededError
from ..team import AgentTeam

if TYPE_CHECKING:
    from .facade import ATTManager


class FailoverService:
    """Owns automatic and parent-governed model failover."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    async def handle_failover(
        self, agent: Agent, team: AgentTeam, error: TokenLimitExceededError
    ) -> bool:
        """
        Handles client failover for an agent when a token limit is reached.
        Returns True if hot-swap succeeded and caller should retry.
        """
        manager = self.manager
        old_model = manager.resolve_runtime_model_alias(agent.llm_client)
        policy = manager.config.failover_policy

        def has_binding(alias: str) -> bool:
            if alias in manager.llm_clients:
                return True
            if alias in manager.model_configs and manager.generator_handler:
                return True
            if alias == "default":
                return bool(
                    manager.generator_handler or getattr(manager.root_ai, "llm_client", None)
                )
            return False

        parent_team = team.parent_team or manager.find_parent_team(team)

        candidates = []
        required_tokens = max(1, getattr(error, "required_tokens", 1))
        for name in manager.config.model_token_limits.keys():
            if name == old_model:
                continue
            if not has_binding(name):
                continue
            available = manager.token_budget.available(name)
            if available is not None and available >= required_tokens:
                candidates.append(name)
        if (
            "default" not in manager.config.model_token_limits
            and "default" not in candidates
            and old_model != "default"
            and has_binding("default")
        ):
            candidates.append("default")

        selected_model = None

        if policy == "auto":
            if candidates:
                selected_model = candidates[0]
            else:
                manager.logger.error(
                    f"Failover failed: No candidate models with remaining budget found."
                )
                return False

        elif policy == "parent":
            from ..communication import ApprovalPrincipal

            if not candidates:
                manager.logger.error("Parent-governed failover has no eligible model candidates.")
                return False
            principal = (
                ApprovalPrincipal(kind="agent_team", principal_id=parent_team.team_id)
                if parent_team is not None
                else ApprovalPrincipal(kind="agent", principal_id=manager.root_ai.agent_id)
            )
            if principal.kind == "agent" and principal.principal_id == agent.agent_id:
                manager.logger.error("Parent-governed failover cannot re-enter the failing Agent.")
                return False
            if principal.kind == "agent_team" and any(
                member.agent_id == agent.agent_id for member in parent_team.members
            ):
                manager.logger.error(
                    "Parent-governed failover cannot re-enter the failing Agent "
                    "through a shared parent AgentTeam membership."
                )
                return False
            prompt = (
                "Select a replacement model for an Agent whose token budget is "
                "exhausted.\n\n"
                f"Child AgentTeam: {team.team_id}\n"
                f"Agent: {agent.name} ({agent.role})\n"
                f"Exhausted model: {old_model}\n"
                f"Required tokens: {required_tokens}\n"
            )
            try:
                if principal.kind == "agent":
                    decision = await asyncio.wait_for(
                        manager.broker.decision_provider.decide_agent_model(
                            principal, prompt, candidates
                        ),
                        timeout=manager.config.parent_failover_timeout_seconds,
                    )
                else:
                    decision = await asyncio.wait_for(
                        manager.broker.decision_provider.decide_team_model(
                            principal, prompt, candidates
                        ),
                        timeout=manager.config.parent_failover_timeout_seconds,
                    )
            except asyncio.TimeoutError:
                manager.logger.error("Parent-governed failover did not complete before timeout.")
                return False
            except Exception as exc:
                manager.logger.error("Parent-governed failover failed closed: %s", exc)
                return False
            if decision.status != "approved" or decision.selected_value not in candidates:
                manager.logger.error(
                    "Parent-governed failover failed closed: %s",
                    decision.reason,
                )
                return False
            selected_model = decision.selected_value

        if not selected_model:
            manager.logger.error("No failover model selected.")
            return False

        new_client = None
        if selected_model in manager.llm_clients:
            new_client = manager.llm_clients[selected_model]
        elif selected_model in manager.model_configs and manager.generator_handler:
            new_client = HandlerClientAdapter(selected_model, manager.generator_handler)
            config = manager.model_configs.get(selected_model)
            if config:
                new_client._supports_native = config.get("supports_native_tool_calling", False)
        elif selected_model == "default" and has_binding("default"):
            new_client = ManagerDefaultClientAdapter(manager)
        else:
            manager.logger.error("Failover model %r has no runtime binding.", selected_model)
            return False

        agent.llm_client = new_client

        agent_status = f"Failover: Switched to {selected_model}"
        team.set_status(agent.name, agent_status)
        manager._emit_callback("on_status_change", agent.name, agent_status)

        if manager.on_log_append:
            log_title = f"[SYSTEM ALERT] Model Failover Event | {agent.name}"
            log_content = (
                f"AGENT: {agent.name}\n"
                f"ROLE: {agent.role}\n"
                f"TEAM: {team.team_id}\n"
                f"FAILOVER POLICY: {policy}\n"
                f"ACTION: Switched client from Model '{old_model}' to Model '{selected_model}' due to budget exhaustion ({error})."
            )
            manager._emit_callback(
                "on_log_append",
                team.team_id,
                log_title,
                log_content,
                team.chapter_num,
            )

        manager._emit_callback(
            "on_system_event",
            "model_failover",
            {
                "agent_name": agent.name,
                "team_id": team.team_id,
                "old_model": old_model,
                "new_model": selected_model,
                "reason": str(error),
            },
        )

        manager.logger.warning(
            f"[FAILOVER SUCCESS] Switched Agent '{agent.name}' from Model '{old_model}' to Model '{selected_model}'. Retrying turn."
        )
        return True
