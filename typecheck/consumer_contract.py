"""Static contract exercised by mypy against the installed public package."""

from typing import Any, Dict, List, Optional, Union

from typing_extensions import assert_type

from ai_team_team import (
    ATTConfig,
    DiscussionResult,
    LLMClientProto,
    LLMResponse,
    Tool,
    ToolResult,
)


class ThirdPartyProviderAdapter:
    """Minimal provider-neutral adapter implemented by a package consumer."""

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.7,
        require_json: bool = False,
    ) -> LLMResponse:
        del prompt, system_instruction, tools, max_output_tokens, temperature
        del require_json
        return LLMResponse(text="done")

    def supports_native_tool_calling(self) -> bool:
        return True

    def supports_output_token_limit(self) -> bool:
        return True


client: LLMClientProto = ThirdPartyProviderAdapter()
config = ATTConfig(model_token_limits={"default": 4096})
tool = Tool(name="noop", description="No operation.", func=lambda: None)

assert_type(client, LLMClientProto)
assert_type(config.model_token_limits["default"], int)
assert_type(tool.json_schema, Dict[str, Any])
assert_type(ToolResult("call-1", "noop", "done"), ToolResult)
assert_type(DiscussionResult, type[DiscussionResult])
