from typing import Protocol, Optional

class LLMClientProto(Protocol):
    """Protocol defining the standard interface for LLM client generation."""
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> str:
        """Generates text from the LLM model."""
        ...

from .core import Agent, AgentTeam, ATTManager, ATTConfig
from .tool import Tool
from .gated_reader import GatedFileReader
from .clients import OpenAIClient, GoogleGenAIClient, AnthropicClient

__all__ = [
    "Agent",
    "AgentTeam",
    "ATTConfig",
    "ATTManager",
    "Tool",
    "GatedFileReader",
    "LLMClientProto",
    "OpenAIClient",
    "GoogleGenAIClient",
    "AnthropicClient",
]
