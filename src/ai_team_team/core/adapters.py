import inspect
import json
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
                return self.handler.supports_native_tool_calling() is True
            except Exception:
                pass
        return getattr(self, "_supports_native", False) is True

    def supports_output_token_limit(self) -> Any:
        try:
            signature = inspect.signature(self.handler)
        except (TypeError, ValueError):
            return False
        if (
            "max_output_tokens" in signature.parameters
            or "max_tokens" in signature.parameters
        ):
            return "max_output_tokens"
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return "max_output_tokens"
        return False

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> LLMResponse:
        try:
            sig = inspect.signature(self.handler)
        except (TypeError, ValueError):
            sig = None
        kwargs = {
            "model_name": self.model_name,
            "prompt": prompt,
            "system_instruction": system_instruction,
            "temperature": temperature,
            "require_json": require_json
        }
        if sig is not None and (
            "tools" in sig.parameters
            or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in sig.parameters.values()
            )
        ):
            kwargs["tools"] = tools
        if sig is not None and max_output_tokens is not None:
            if "max_output_tokens" in sig.parameters:
                kwargs["max_output_tokens"] = max_output_tokens
            elif "max_tokens" in sig.parameters:
                kwargs["max_tokens"] = max_output_tokens
            elif any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in sig.parameters.values()
            ):
                kwargs["max_output_tokens"] = max_output_tokens

        res = self.handler(**kwargs)
        if inspect.isawaitable(res):
            res = await res
        
        if isinstance(res, LLMResponse):
            return res
        elif isinstance(res, str):
            return LLMResponse(text=res)
        elif isinstance(res, dict):
            text = res.get("text")
            t_calls = []
            for tc in res.get("tool_calls", []):
                function = tc.get("function") or {}
                name = tc.get("name") or function.get("name")
                arguments = tc.get("arguments", function.get("arguments", {}))
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"Invalid JSON arguments for tool '{name}': {exc}"
                        ) from exc
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    raise ValueError(
                        f"Tool arguments for '{name}' must be an object."
                    )
                t_calls.append(ToolCall(
                    call_id=tc.get("id"),
                    name=name,
                    arguments=arguments,
                    raw=tc.get("raw")
                ))
            return LLMResponse(
                text=text,
                tool_calls=t_calls,
                usage=res.get("usage"),
            )
            
        raise ValueError(f"Invalid response type returned by generator handler: {type(res)}")

class ManagerDefaultClientAdapter:
    """Wraps the manager's default global generator handler callback."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager

    def supports_native_tool_calling(self) -> bool:
        if self.manager.generator_handler:
            config = self.manager.model_configs.get("default")
            if (
                config
                and config.get("supports_native_tool_calling") is True
            ):
                return True
            if hasattr(self.manager.generator_handler, "supports_native_tool_calling"):
                try:
                    return (
                        self.manager.generator_handler
                        .supports_native_tool_calling() is True
                    )
                except Exception:
                    pass
        
        if self.manager.root_ai and self.manager.root_ai.llm_client and self.manager.root_ai.llm_client is not self:
            if hasattr(self.manager.root_ai.llm_client, "supports_native_tool_calling"):
                try:
                    return (
                        self.manager.root_ai.llm_client
                        .supports_native_tool_calling() is True
                    )
                except Exception:
                    pass
        return False

    def supports_output_token_limit(self) -> Any:
        target = self.manager.generator_handler
        if target is not None:
            return HandlerClientAdapter(
                "default", target
            ).supports_output_token_limit()
        root_client = getattr(self.manager.root_ai, "llm_client", None)
        if root_client is not None and root_client is not self:
            from .utils import _output_limit_parameter

            return (
                "max_output_tokens"
                if _output_limit_parameter(root_client)
                else False
            )
        return False

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        max_output_tokens: Optional[int] = None,
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
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                require_json=require_json
            )

        if self.manager.root_ai and self.manager.root_ai.llm_client and type(self.manager.root_ai.llm_client) is not ManagerDefaultClientAdapter:
            generate = self.manager.root_ai.llm_client.generate
            kwargs = {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "temperature": temperature,
                "require_json": require_json,
            }
            try:
                signature = inspect.signature(generate)
            except (TypeError, ValueError):
                signature = None
            if signature is not None and (
                "tools" in signature.parameters
                or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
            ):
                kwargs["tools"] = tools
            from .utils import _output_limit_parameter

            output_parameter = _output_limit_parameter(
                self.manager.root_ai.llm_client
            )
            if output_parameter and max_output_tokens is not None:
                kwargs[output_parameter] = max_output_tokens
            result = generate(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        raise ValueError("No default client or generator handler configured on ATTManager.")
