"""Static contract exercised by mypy against the installed public package."""

from typing import Any, Dict, List, Optional, Union

from typing_extensions import assert_type

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTeam,
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


def create_shared_memberships(
    manager: ATTManager,
    creator: Agent,
    shared: Agent,
    new_members: Dict[str, Dict[str, Any]],
) -> tuple[AgentTeam, AgentTeam]:
    """Exercise both role-neutral shared-membership entry points."""
    by_object = manager.create_agent_team(
        creator,
        member_configs=new_members,
        existing_members=[shared],
    )
    by_id = creator.launch_att(
        manager,
        member_configs=new_members,
        existing_member_ids=[shared.agent_id],
    )
    return by_object, by_id
