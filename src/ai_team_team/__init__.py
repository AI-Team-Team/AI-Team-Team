from typing import Protocol, Optional, Union, List, Dict, Any, TYPE_CHECKING
from .core import ToolCall, ToolResult, LLMResponse

if TYPE_CHECKING:
    from .tool import Tool

class LLMClientProto(Protocol):
    """Protocol defining the standard interface for LLM client generation."""
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List["Tool"]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> LLMResponse:
        """Generates a text completion or tool calls from the LLM model."""
        ...

    def supports_native_tool_calling(self) -> bool:
        """Returns True if the client/model configuration natively supports structured function calling."""
        ...

    def supports_output_token_limit(self) -> Union[bool, str]:
        """Reports support for max_output_tokens or max_tokens requests."""
        ...

from .core import (
    Agent,
    AgentTeam,
    ATTManager,
    ATTConfig,
    AgreementDirection,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationBallot,
    CommunicationConfig,
    CommunicationOperationResult,
    CommunicationRequest,
    CommunicationRequestStatus,
    LineageApprovalCommunicationConfig,
    ParentApprovalCommunicationConfig,
    PermissiveCommunicationConfig,
    EpisodicMemoryConfig,
    TurnFailurePolicyConfig,
    AgentTurnResult,
    AgentTurnStatus,
    DiscussionResult,
    DiscussionRoundResult,
    DiscussionStatus,
    OperationalStatus,
    ToolFailureSummary,
    ToolResultStatus,
    PeerMessage,
    AgentMemoryCard,
    AgentMemorySegment,
    MemoryCardStatus,
    MemoryIndexStatus,
    MemoryOperationResult,
    MemoryRecallResult,
    MemorySearchItem,
    MemorySearchResult,
    RetainedMemoryReference,
    SystemMemoryEvent,
    ATTException,
    LLMGenerationError,
)
from .core.exceptions import (
    AmbiguousTeamContextError,
    DatabaseOwnershipError,
    LLMRateLimitError,
    LLMServiceError,
    StatePersistenceError,
    StateRestoreError,
    TokenLimitExceededError,
    TransientLLMError,
    AgentTurnIncompleteError,
    ToolArgumentError,
    ToolBusinessError,
    ToolPermissionError,
    RetryableToolError,
)
from .supervision import AuditResult, AuditStatus
from .tool import Tool
from .gated_reader import GatedFileReader
from .doc_library import DocumentLibrary

__all__ = [
    "Agent",
    "AgentTeam",
    "ATTConfig",
    "PermissiveCommunicationConfig",
    "EpisodicMemoryConfig",
    "ParentApprovalCommunicationConfig",
    "LineageApprovalCommunicationConfig",
    "ApprovalPrincipal",
    "AgreementDirection",
    "CommunicationRequest",
    "CommunicationRequestStatus",
    "CommunicationApproval",
    "CommunicationApprovalStatus",
    "CommunicationBallot",
    "CommunicationAgreement",
    "CommunicationOperationResult",
    "PeerMessage",
    "AgentMemoryCard",
    "AgentMemorySegment",
    "MemoryCardStatus",
    "MemoryIndexStatus",
    "MemoryOperationResult",
    "MemoryRecallResult",
    "MemorySearchItem",
    "MemorySearchResult",
    "RetainedMemoryReference",
    "SystemMemoryEvent",
    "CommunicationConfig",
    "TurnFailurePolicyConfig",
    "ATTManager",
    "Tool",
    "GatedFileReader",
    "LLMClientProto",
    "ATTException",
    "LLMGenerationError",
    "TokenLimitExceededError",
    "StateRestoreError",
    "StatePersistenceError",
    "DatabaseOwnershipError",
    "AmbiguousTeamContextError",
    "TransientLLMError",
    "AgentTurnIncompleteError",
    "ToolArgumentError",
    "ToolBusinessError",
    "ToolPermissionError",
    "RetryableToolError",
    "LLMRateLimitError",
    "LLMServiceError",
    "AuditResult",
    "AuditStatus",
    "OperationalStatus",
    "AgentTurnResult",
    "AgentTurnStatus",
    "DiscussionResult",
    "DiscussionRoundResult",
    "DiscussionStatus",
    "ToolFailureSummary",
    "ToolResultStatus",
    "DocumentLibrary",
    "ToolCall",
    "ToolResult",
    "LLMResponse",
]
