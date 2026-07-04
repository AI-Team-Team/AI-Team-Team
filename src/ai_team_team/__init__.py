from typing import Protocol, Optional, Union, List, Dict, Any
from .core import ToolCall, ToolResult, LLMResponse

class LLMClientProto(Protocol):
    """Protocol defining the standard interface for LLM client generation."""
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> LLMResponse:
        """Generates a text completion or tool calls from the LLM model."""
        ...

    def supports_native_tool_calling(self) -> bool:
        """Returns True if the client/model configuration natively supports structured function calling."""
        ...

from .core import Agent, AgentTeam, ATTManager, ATTConfig, ATTException, LLMGenerationError
from .core.exceptions import TokenLimitExceededError
from .tool import Tool
from .gated_reader import GatedFileReader
from .doc_library import DocumentLibrary

__all__ = [
    "Agent",
    "AgentTeam",
    "ATTConfig",
    "ATTManager",
    "Tool",
    "GatedFileReader",
    "LLMClientProto",
    "ATTException",
    "LLMGenerationError",
    "TokenLimitExceededError",
    "DocumentLibrary",
    "ToolCall",
    "ToolResult",
    "LLMResponse",
]
