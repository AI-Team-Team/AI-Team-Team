from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolResultStatus(str, Enum):
    """Provider-neutral outcome of one tool invocation."""

    SUCCESS = "success"
    INVALID_ARGUMENTS = "invalid_arguments"
    DENIED = "denied"
    BUSINESS_ERROR = "business_error"
    TRANSIENT_ERROR = "transient_error"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN_TOOL = "unknown_tool"


class ToolFailureSummary(BaseModel):
    """Privacy-safe metadata for a failed tool invocation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tool_name: str
    status: ToolResultStatus
    error_kind: str
    attempts: int = Field(ge=1)


class AgentTurnStatus(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class DiscussionStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"


class AuditStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class OperationalStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class AuditResult(BaseModel):
    """Content-health and runtime-health results for one discussion."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: AuditStatus
    reason: str
    cause: Optional[str] = None
    operational_status: OperationalStatus = OperationalStatus.HEALTHY
    operational_reason: str = "All member turns completed."

    def __init__(
        self,
        status: Optional[AuditStatus] = None,
        reason: Optional[str] = None,
        cause: Optional[str] = None,
        **data: Any,
    ) -> None:
        if status is not None:
            data["status"] = status
        if reason is not None:
            data["reason"] = reason
        if cause is not None:
            data["cause"] = cause
        super().__init__(**data)


class AgentTurnResult(BaseModel):
    """Structured result of one Agent reasoning turn."""

    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str
    team_id: str
    turn_id: Optional[str] = None
    discussion_id: Optional[str] = None
    round_number: Optional[int] = None
    status: AgentTurnStatus
    answer: Optional[str] = None
    error_kind: Optional[str] = None
    reason: Optional[str] = None
    tool_failures: List[ToolFailureSummary] = Field(default_factory=list)

    @property
    def text(self) -> str:
        if self.status is AgentTurnStatus.COMPLETED:
            return self.answer or ""
        return f"[Turn incomplete: {self.reason or 'unknown member failure'}]"


class DiscussionRoundResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    round_number: int = Field(ge=1)
    turns: List[AgentTurnResult]


class DiscussionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    team_id: str
    discussion_id: str
    status: DiscussionStatus
    transcript: str
    rounds: List[DiscussionRoundResult]
    audit: AuditResult

class ToolCall:
    """Represents a structured tool calling request from the model."""
    def __init__(self, call_id: str, name: str, arguments: Dict[str, Any], raw: Optional[Any] = None):
        self.call_id = call_id
        self.name = name
        self.arguments = arguments
        self.raw = raw

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments
            }
        }

class ToolResult:
    """Represents a structured tool execution result."""
    def __init__(
        self,
        tool_call_id: str,
        name: str,
        content: str,
        raw: Optional[Any] = None,
        *,
        status: ToolResultStatus = ToolResultStatus.SUCCESS,
        error_kind: Optional[str] = None,
        attempts: int = 1,
    ):
        self.tool_call_id = tool_call_id
        self.name = name
        self.content = content
        self.raw = raw
        self.status = status
        self.error_kind = error_kind
        self.attempts = attempts

    @property
    def failed(self) -> bool:
        return self.status is not ToolResultStatus.SUCCESS

    def failure_summary(self) -> Optional[ToolFailureSummary]:
        if not self.failed:
            return None
        return ToolFailureSummary(
            tool_name=self.name,
            status=self.status,
            error_kind=self.error_kind or self.status.value,
            attempts=self.attempts,
        )

class LLMResponse:
    """Unified wrapper around LLM response containing text and/or tool calls."""
    def __init__(
        self,
        text: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        usage: Optional[Any] = None,
    ):
        self.text = text
        self.tool_calls = tool_calls or []
        self.usage = usage
