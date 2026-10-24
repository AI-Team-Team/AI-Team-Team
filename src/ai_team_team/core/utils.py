import asyncio
import inspect
import json
import logging
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Union, List, Dict, Optional, Any
from .exceptions import (
    LLMGenerationError,
    TransientLLMError,
)

logger = logging.getLogger("ATT.CoreUtils")

if TYPE_CHECKING:
    from ai_team_team.tool import Tool


_RETRYABLE_PROVIDER_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "InternalServerError",
    "RateLimitError",
    "ReadTimeout",
    "ServiceUnavailableError",
}


async def _invoke_sync_provider(function, **kwargs):
    """Retain local ownership until an uncancellable synchronous call ends."""
    worker = asyncio.create_task(asyncio.to_thread(function, **kwargs))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
    result = worker.result()
    if cancelled:
        if inspect.iscoroutine(result):
            result.close()
        raise asyncio.CancelledError
    return result


def _is_retryable_llm_error(error: BaseException) -> bool:
    """Classifies transient failures by type or explicit provider metadata."""
    if isinstance(
        error,
        (TransientLLMError, TimeoutError, ConnectionError),
    ):
        return True
    if getattr(error, "retryable", None) is True:
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    if status == 429 or (
        isinstance(status, int) and 500 <= status <= 599
    ):
        return True
    return type(error).__name__ in _RETRYABLE_PROVIDER_ERROR_NAMES


def _output_limit_parameter(llm_client: Any) -> Optional[str]:
    support_check = getattr(llm_client, "supports_output_token_limit", None)
    if callable(support_check):
        try:
            supported = support_check()
            if supported in {"max_output_tokens", "max_tokens"}:
                return str(supported)
            if supported is not True:
                return None
        except Exception:
            return None
    generate = getattr(llm_client, "generate", llm_client)
    try:
        signature = inspect.signature(generate)
    except (TypeError, ValueError):
        return None
    if "max_output_tokens" in signature.parameters:
        return "max_output_tokens"
    if "max_tokens" in signature.parameters:
        return "max_tokens"
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return "max_output_tokens"
    return None


def _configured_output_limit(manager: Any, alias: str) -> int:
    configured = manager.config.model_max_output_tokens.get(alias)
    if configured is None:
        model_config = manager.model_configs.get(alias, {})
        configured = model_config.get(
            "max_output_tokens", model_config.get("max_tokens")
        )
    if configured is None:
        configured = manager.config.default_max_output_tokens
    return int(configured)


def _usage_field(usage: Any, *names: str) -> Optional[int]:
    for name in names:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, int(value))
    return None


def _actual_usage(
    source: Any,
    fallback_prompt_tokens: int,
    fallback_output_tokens: int,
) -> int:
    usage = source.get("usage") if isinstance(source, dict) else getattr(
        source, "usage", None
    )
    if usage is None:
        return fallback_prompt_tokens + fallback_output_tokens
    total = _usage_field(usage, "total_tokens", "total_token_count")
    if total is not None:
        return total
    prompt = _usage_field(usage, "prompt_tokens", "input_tokens")
    output = _usage_field(usage, "completion_tokens", "output_tokens")
    return (
        fallback_prompt_tokens if prompt is None else prompt
    ) + (
        fallback_output_tokens if output is None else output
    )


def _accepts_keyword(callable_obj: Any, name: str) -> bool:
    """Returns whether a callable explicitly or variadically accepts a keyword."""
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _serialize_tool_definition(tool: Any) -> str:
    """Returns the stable provider-neutral definition sent for one Tool."""
    if hasattr(tool, "json_schema"):
        value = {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "json_schema"),
        }
    elif isinstance(tool, Mapping):
        value = dict(tool)
    else:
        value = tool
    return json.dumps(value, ensure_ascii=False, default=str)


def _count_request_input_tokens(
    manager: Any,
    model_alias: str,
    prompt: Union[str, List[Dict[str, str]]],
    system_instruction: Optional[str],
    tools: Optional[List["Tool"]],
) -> int:
    """Estimates all explicit model-bound request components."""
    prompt_text = (
        prompt
        if isinstance(prompt, str)
        else json.dumps(prompt, ensure_ascii=False, default=str)
    )
    components = [prompt_text]
    if system_instruction:
        components.append(system_instruction)
    components.extend(_serialize_tool_definition(tool) for tool in tools or [])
    return sum(manager.count_tokens(component, model_alias) for component in components)

async def generate_with_retry(
    llm_client: Any,
    prompt: Union[str, List[Dict[str, str]]],
    system_instruction: Optional[str] = None,
    temperature: float = 0.3,
    require_json: bool = False,
    retries: int = 3,
    backoff_factor: float = 1.5,
    tools: Optional[List["Tool"]] = None,
    return_response_obj: bool = False,
    manager: Optional[Any] = None,
    model_alias: Optional[str] = None
) -> Union[str, Any]:
    """Invokes LLM client generation with exponential backoff on transient errors."""
    from .response import LLMResponse
    generate_callable = getattr(llm_client, "generate", llm_client)
    transmitted_tools = tools if tools is not None and _accepts_keyword(generate_callable, "tools") else None
    if manager is not None:
        session = manager._activity.current.get()
        agent = manager._agents_by_id.get(session.agent_id) if session is not None else None
        if session is None or agent is None or agent.llm_client is not llm_client:
            raise RuntimeError("Manager-backed inference requires the exact current personal activity.")
        if model_alias is not None and model_alias != manager.resolve_runtime_model_alias(llm_client):
            raise ValueError("A caller cannot override its current model's resource identity.")
        response = await manager._activity.models.generate(
            session, client=llm_client, prompt=prompt, system_instruction=system_instruction,
            tools=transmitted_tools, temperature=temperature, require_json=require_json,
            audit_profile=session.audit_profile,
        )
        return response if return_response_obj else response.text or ""

    if type(retries) is not int or retries < 0:
        raise ValueError("retries must be a non-negative integer.")
    if type(backoff_factor) not in {int, float} or not math.isfinite(backoff_factor) or backoff_factor < 0:
        raise ValueError("backoff_factor must be a finite non-negative number.")
    kwargs = {"prompt": prompt, "system_instruction": system_instruction,
              "temperature": temperature, "require_json": require_json}
    if transmitted_tools is not None:
        kwargs["tools"] = transmitted_tools
    for attempt in range(retries + 1):
        try:
            if inspect.iscoroutinefunction(generate_callable):
                response = await generate_callable(**kwargs)
            else:
                response = await _invoke_sync_provider(generate_callable, **kwargs)
                if inspect.isawaitable(response):
                    response = await response
            if isinstance(response, str):
                response = LLMResponse(text=response)
            if not isinstance(response, LLMResponse):
                raise TypeError("A model client must return text or LLMResponse.")
            return response if return_response_obj else response.text or ""
        except asyncio.CancelledError:
            raise
        except LLMGenerationError:
            raise
        except Exception as error:
            if attempt == retries or not _is_retryable_llm_error(error):
                raise LLMGenerationError(
                    f"LLM generation failed after {attempt + 1} attempt(s) with {type(error).__name__}."
                ) from error
            delay = float(backoff_factor) * 2 ** attempt
            logger.warning("Standalone provider request failed with %s; retrying in %.2fs.", type(error).__name__, delay)
            if delay:
                await asyncio.sleep(delay)
    raise LLMGenerationError("The standalone model sequence did not return a response.")
