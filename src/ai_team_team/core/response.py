from typing import Dict, Any, List, Optional

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
    def __init__(self, tool_call_id: str, name: str, content: str, raw: Optional[Any] = None):
        self.tool_call_id = tool_call_id
        self.name = name
        self.content = content
        self.raw = raw

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
