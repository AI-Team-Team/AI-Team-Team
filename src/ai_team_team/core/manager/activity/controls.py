"""Current-person controls, applied only after the complete captured batch."""

from ai_team_team.core.activity.contracts import (
    ActivityIntent,
    CountdownBounds,
    OperationScope,
    SleepIntent,
    ToolExecutionContract,
    SuppressionPreference,
)
from ai_team_team.core.exceptions import ToolArgumentError, ToolPermissionError
from ai_team_team.tool import Tool


class ControlMixin:
    def control_tools(self, session):
        def current():
            agent = self.manager._active_tool_agent.get()
            if (
                self.current.get() is not session
                or agent is None
                or agent.agent_id != session.agent_id
                or self.manager._agents_by_id.get(agent.agent_id) is not agent
            ):
                raise ToolPermissionError(
                    "Activity controls require the current registered person."
                )
            from .values import ScopeUnavailable
            try:
                self.check_generation(session)
            except ScopeUnavailable as error:
                raise ToolPermissionError("The original AgentTeam scope ended before this control was accepted.") from error

        def set_activity_intent(intent: ActivityIntent):
            """Choose idle or finite sleep; ordinary answers otherwise continue activity."""
            current()
            if session.audit_profile is not None and intent.kind != "idle":
                raise ToolPermissionError("A bounded audit may choose idle but cannot sleep.")
            if isinstance(intent, SleepIntent):
                config = self.manager.config.activity
                try:
                    intent.check_bounds(
                        CountdownBounds(
                            minimum_minutes=config.minimum_sleep_minutes,
                            maximum_minutes=config.maximum_sleep_minutes,
                        )
                    )
                except ValueError as error:
                    raise ToolArgumentError(str(error)) from error
                for condition in intent.early_conditions:
                    if condition.kind == "message":
                        registry = (
                            self.manager._agents_by_id
                            if condition.source_kind == "agent"
                            else self.manager.teams
                        )
                        if condition.source_id not in registry:
                            raise ToolArgumentError("A sleep condition refers to a missing source.")
                        if condition.source_kind == "agent_team":
                            self.validate_scope(
                                session.agent_id,
                                {"kind": "agent_team", "team_id": condition.source_id},
                            )
                    else:
                        row = self.manager._records.index.get(
                            ("executions", (condition.execution_id,))
                        )
                        if row is None or row.values["agent_id"] != session.agent_id:
                            raise ToolPermissionError(
                                "A sleep condition must identify an owned execution."
                            )
            session.pending_intent = intent
            return {"status": "PENDING_BOUNDARY", "intent": intent.kind}

        def set_operation_scope(scope: OperationScope):
            """Request one validated personal or current-member AT scope after this batch."""
            current()
            self.validate_scope(session.agent_id, scope)
            session.pending_scope = scope
            return {"status": "PENDING_BOUNDARY", "scope": scope.model_dump(mode="json")}

        async def set_notification_suppression(preference: SuppressionPreference):
            """Suppress ordinary reminders permanently or for a bounded countdown; sources remain delivered and unread."""
            current()
            return await self.set_suppression(preference, actor=self.manager._active_tool_agent.get())

        def list_notification_suppressions(active_only: bool = True):
            """List only your own ordinary-reminder suppression preferences."""
            current()
            return self.list_suppressions(actor=self.manager._active_tool_agent.get(), active_only=active_only)

        async def remove_notification_suppression(preference_id: str):
            """Remove your preference and summarize eligible unread information by source and count only."""
            current()
            return await self.remove_suppression(preference_id, actor=self.manager._active_tool_agent.get())

        contract = ToolExecutionContract(
            effects=("self_modification",),
            background_allowed=False,
            required_scope="personal",
            mutation_safety="managed_lease",
        )
        tools = {
            name: Tool(name=name, func=func, execution_contract=contract,
                       resource_resolver=lambda scope, arguments: ())
            for name, func in (
                ("set_activity_intent", set_activity_intent),
                ("set_operation_scope", set_operation_scope),
                ("set_notification_suppression", set_notification_suppression),
                ("list_notification_suppressions", list_notification_suppressions),
                ("remove_notification_suppression", remove_notification_suppression),
            )
        }
        if session.audit_profile is not None:
            tools = {"set_activity_intent": tools["set_activity_intent"]}
        return tools
