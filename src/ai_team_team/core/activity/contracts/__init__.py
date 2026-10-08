"""Frozen Phase 0 value contracts, not a second execution engine."""

from .api import ActivityRuntimeAPI, ChatMessagePage, ChatMessageSummary
from .bindings import RuntimeClock
from .execution import (
    ActivityAdmission,
    ActivityCheckpoint,
    ActivityView,
    BackgroundTaskHandle,
    ExecutionObservation,
    ToolExecutionContract,
)
from .intent import (
    ActivityIntent,
    CountdownBounds,
    ExecutionWakeCondition,
    IdleIntent,
    MessageWakeCondition,
    SleepIntent,
    SuppressionPreference,
    WakeDuration,
)
from .notifications import (
    NotificationReference,
    NotificationSource,
    PresentationClaim,
    SourceDeliveryReceipt,
)
from .scope import AgentTeamScope, InvocationScope, OperationScope, PersonalScope

TARGET_STATE_SCHEMA_VERSION = "12"

__all__ = [
    "ActivityAdmission",
    "ActivityCheckpoint",
    "ActivityIntent",
    "ActivityRuntimeAPI",
    "ActivityView",
    "BackgroundTaskHandle",
    "ChatMessagePage",
    "ChatMessageSummary",
    "AgentTeamScope",
    "CountdownBounds",
    "ExecutionObservation",
    "ExecutionWakeCondition",
    "IdleIntent",
    "InvocationScope",
    "MessageWakeCondition",
    "NotificationReference",
    "NotificationSource",
    "OperationScope",
    "PersonalScope",
    "PresentationClaim",
    "RuntimeClock",
    "SleepIntent",
    "SourceDeliveryReceipt",
    "SuppressionPreference",
    "TARGET_STATE_SCHEMA_VERSION",
    "ToolExecutionContract",
    "WakeDuration",
]
