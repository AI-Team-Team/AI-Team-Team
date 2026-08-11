from typing import Protocol, Optional, Union, List, Dict, Any
from .core import ToolCall, ToolResult, LLMResponse

class LLMClientProto(Protocol):
    """Protocol defining the standard interface for LLM client generation."""
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
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
    PeerMessage,
    ATTException,
    LLMGenerationError,
)
from .core.exceptions import (
    AmbiguousTeamContextError,
    DatabaseOwnershipError,
    LLMRateLimitError,
    LLMServiceError,
    StateRestoreError,
    TokenLimitExceededError,
    TransientLLMError,
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
    "CommunicationConfig",
    "ATTManager",
    "Tool",
    "GatedFileReader",
    "LLMClientProto",
    "ATTException",
    "LLMGenerationError",
    "TokenLimitExceededError",
    "StateRestoreError",
    "DatabaseOwnershipError",
    "AmbiguousTeamContextError",
    "TransientLLMError",
    "LLMRateLimitError",
    "LLMServiceError",
    "AuditResult",
    "AuditStatus",
    "DocumentLibrary",
    "ToolCall",
    "ToolResult",
    "LLMResponse",
]
