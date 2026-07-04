import inspect
from typing import Union, List, Dict, Optional, Any, Callable
from ai_team_team.core.response import ToolCall, LLMResponse

class HandlerClientAdapter:
    """Wraps a global generator handler callback to conform to LLMClientProto."""
    def __init__(self, model_name: str, handler: Callable[..., str]):
        self.model_name = model_name
        self.handler = handler
        self._supports_native = False

    def supports_native_tool_calling(self) -> bool:
        if hasattr(self.handler, "supports_native_tool_calling"):
            try:
                return self.handler.supports_native_tool_calling()
            except Exception:
                pass
        return getattr(self, "_supports_native", False)

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> LLMResponse:
        sig = inspect.signature(self.handler)
        kwargs = {
            "model_name": self.model_name,
            "prompt": prompt,
            "system_instruction": system_instruction,
            "temperature": temperature,
            "require_json": require_json
        }
        if "tools" in sig.parameters:
            kwargs["tools"] = tools

        res = await self.handler(**kwargs)
        
        if isinstance(res, LLMResponse):
            return res
        elif isinstance(res, str):
            return LLMResponse(text=res)
        elif isinstance(res, dict):
            text = res.get("text")
            t_calls = []
            for tc in res.get("tool_calls", []):
                t_calls.append(ToolCall(
                    call_id=tc.get("id"),
                    name=tc.get("name"),
                    arguments=tc.get("arguments"),
                    raw=tc.get("raw")
                ))
            return LLMResponse(text=text, tool_calls=t_calls)
            
        raise ValueError(f"Invalid response type returned by generator handler: {type(res)}")

class ManagerDefaultClientAdapter:
    """Wraps the manager's default global generator handler callback."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager

    def supports_native_tool_calling(self) -> bool:
        if self.manager.generator_handler:
            config = self.manager.model_configs.get("default")
            if config and config.get("supports_native_tool_calling"):
                return True
            if hasattr(self.manager.generator_handler, "supports_native_tool_calling"):
                try:
                    return self.manager.generator_handler.supports_native_tool_calling()
                except Exception:
                    pass
        
        if self.manager.root_ai and self.manager.root_ai.llm_client and self.manager.root_ai.llm_client is not self:
            if hasattr(self.manager.root_ai.llm_client, "supports_native_tool_calling"):
                try:
                    return bool(self.manager.root_ai.llm_client.supports_native_tool_calling())
                except Exception:
                    pass
        return False

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> LLMResponse:
        if self.manager.generator_handler:
            temp_adapter = HandlerClientAdapter("default", self.manager.generator_handler)
            default_config = self.manager.model_configs.get("default")
            if default_config:
                temp_adapter._supports_native = default_config.get("supports_native_tool_calling", False)
            return await temp_adapter.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                tools=tools,
                temperature=temperature,
                require_json=require_json
            )

        if self.manager.root_ai and self.manager.root_ai.llm_client and self.manager.root_ai.llm_client is not self:
            if not isinstance(self.manager.root_ai.llm_client, ManagerDefaultClientAdapter):
                return await self.manager.root_ai.llm_client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    tools=tools,
                    temperature=temperature,
                    require_json=require_json
                )
        raise ValueError("No default client or generator handler configured on ATTManager.")
