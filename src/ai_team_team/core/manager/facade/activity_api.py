"""Admission and observation address a person, never a copied team-local actor."""

from typing import Any, Literal, Mapping

from ...agent import Agent
from ...activity.contracts import (
    ActivityAdmission,
    ActivityCheckpoint,
    ActivityView,
    OperationScope,
    RuntimeClock,
    SourceDeliveryReceipt,
    SuppressionPreference,
)


class ActivityAPI:
    async def set_notification_suppression(self, preference: SuppressionPreference, *, actor: Agent | None = None) -> dict[str, Any]:
        return await self._activity.set_suppression(preference, actor=actor)

    def list_notification_suppressions(self, *, actor: Agent | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        return self._activity.list_suppressions(actor=actor, active_only=active_only)

    async def remove_notification_suppression(self, preference_id: str, *, actor: Agent | None = None) -> dict[str, Any]:
        return await self._activity.remove_suppression(preference_id, actor=actor)

    def register_runtime_clock(self, clock: RuntimeClock) -> None:
        self._activity.register_clock(clock)

    async def activate_agent(
        self, agent_id: str, *, scope: OperationScope | None = None
    ) -> ActivityAdmission:
        return await self._activity.activate(agent_id, scope=scope)

    def inspect_agent_activity(self, agent_id: str) -> ActivityView:
        return self._activity.inspect(agent_id)

    async def wait_for_activity_checkpoint(
        self, admission_id: str, *, intent: Literal["continuing", "idle", "sleep"] | None = None
    ) -> ActivityCheckpoint:
        return await self._activity.wait(admission_id, intent=intent)

    async def deliver_agent_mail(
        self, agent_id: str, *, message_type: str, payload: Mapping[str, Any]
    ) -> SourceDeliveryReceipt:
        return await self._activity.deliver_mail(
            agent_id, message_type=message_type, payload=payload
        )

    async def clear_agent_model_unavailability(self, agent_id: str) -> None:
        """Host-only acknowledgement after repairing a model or quota resource."""
        await self._activity.clear_model_unavailability(agent_id)
