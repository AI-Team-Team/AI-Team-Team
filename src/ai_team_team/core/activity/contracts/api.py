"""Host-facing entry points reserved for the common personal runtime."""

from typing import Any, Literal, Mapping, Protocol

from pydantic import Field

from ...agent import Agent
from .base import ContractRecord, Identifier
from .bindings import RuntimeClock
from .execution import ActivityAdmission, ActivityCheckpoint, ActivityView
from .notifications import SourceDeliveryReceipt
from .scope import OperationScope


class ChatMessageSummary(ContractRecord):
    message_id: Identifier
    author_agent_id: Identifier
    version: int = Field(gt=0)
    title: str | None
    preview: str
    unread: bool = True
    withdrawn: bool = False
    frozen: bool = False


class ChatMessagePage(ContractRecord):
    items: tuple[ChatMessageSummary, ...]
    total_count: int = Field(ge=0)
    unread_count: int = Field(ge=0)
    next_cursor: str | None = None


class ActivityRuntimeAPI(Protocol):
    """Host contract; personal methods are implemented before the later chat service."""

    def register_runtime_clock(self, clock: RuntimeClock) -> None: ...

    async def activate_agent(
        self, agent_id: str, *, scope: OperationScope | None = None
    ) -> ActivityAdmission: ...

    def inspect_agent_activity(self, agent_id: str) -> ActivityView: ...

    async def wait_for_activity_checkpoint(
        self, admission_id: str, *, intent: Literal["continuing", "idle", "sleep"] | None = None
    ) -> ActivityCheckpoint: ...

    async def deliver_agent_mail(
        self, agent_id: str, *, message_type: str, payload: Mapping[str, Any]
    ) -> SourceDeliveryReceipt: ...

    def list_team_messages(self, team_id: str, *, actor: Agent) -> ChatMessagePage: ...
