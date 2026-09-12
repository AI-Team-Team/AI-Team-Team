import asyncio
import inspect
import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Union, List, Dict, Optional, Any
from .exceptions import (
    LLMGenerationError,
    TokenLimitExceededError,
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


async def _await_external_llm(awaitable: Any, manager: Optional[Any]) -> Any:
    task = asyncio.current_task()
    if manager is not None:
        if getattr(manager, "_closing", False):
            close_awaitable = getattr(awaitable, "close", None)
            if callable(close_awaitable):
                close_awaitable()
            cancelled = asyncio.CancelledError("ATTManager is closing.")
            setattr(cancelled, "request_sent", False)
            raise cancelled
        if task is not None:
            manager._llm_tasks.add(task)
    try:
        return await awaitable
    finally:
        if manager is not None and task is not None:
            manager._llm_tasks.discard(task)


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
    input_tokens = 0
    resolved_alias = model_alias
    generate_callable = getattr(llm_client, "generate", llm_client)
    transmitted_tools = (
        tools
        if tools is not None and _accepts_keyword(generate_callable, "tools")
        else None
    )

    if manager:
        resolved_alias = (
            resolved_alias
            or manager.resolve_runtime_model_alias(llm_client)
        )
        if resolved_alias in manager.config.model_token_limits:
            input_tokens = _count_request_input_tokens(
                manager,
                resolved_alias,
                prompt,
                system_instruction,
                transmitted_tools,
            )

    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError("retries must be a non-negative integer.")
    if (
        not isinstance(backoff_factor, (int, float))
        or isinstance(backoff_factor, bool)
        or backoff_factor < 0
    ):
        raise ValueError("backoff_factor must be a non-negative number.")
    attempts = retries + 1

    for attempt in range(1, attempts + 1):
        reservation = None
        request_sent = False
        try:
            output_parameter = None
            if (
                manager is not None
                and resolved_alias is not None
                and resolved_alias in manager.config.model_token_limits
            ):
                output_parameter = _output_limit_parameter(llm_client)
                requested_output = _configured_output_limit(
                    manager, resolved_alias
                )
                reservation = manager.token_budget.reserve(
                    resolved_alias,
                    input_tokens,
                    requested_output,
                )
                if reservation is not None and output_parameter is None:
                    manager.token_budget.release(reservation)
                    reservation = None
                    raise LLMGenerationError(
                        "Hard token budgets require an LLM client that "
                        "accepts max_output_tokens or max_tokens."
                    )

            if hasattr(llm_client, "generate"):
                kwargs = {}
                if transmitted_tools is not None:
                    kwargs["tools"] = transmitted_tools
                if output_parameter and reservation is not None:
                    kwargs[output_parameter] = reservation.output_tokens
                request = llm_client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    require_json=require_json,
                    **kwargs
                )
                request_sent = True
                response = await _await_external_llm(
                    request,
                    manager,
                )
            else:
                # Fallback to direct callable
                call_kwargs: Dict[str, Any] = {
                    "prompt": prompt,
                    "system_instruction": system_instruction,
                    "temperature": temperature,
                    "require_json": require_json,
                }
                if transmitted_tools is not None:
                    call_kwargs["tools"] = transmitted_tools
                if output_parameter and reservation is not None:
                    call_kwargs[output_parameter] = reservation.output_tokens
                if asyncio.iscoroutinefunction(llm_client):
                    request = llm_client(**call_kwargs)
                    request_sent = True
                    response = await _await_external_llm(
                        request, manager
                    )
                else:
                    request = asyncio.to_thread(llm_client, **call_kwargs)
                    request_sent = True
                    response = await _await_external_llm(
                        request, manager
                    )
            
            response_text = ""
            if isinstance(response, str):
                response_text = response
            elif isinstance(response, LLMResponse) and response.text is not None:
                response_text = response.text
            elif hasattr(response, "text") and response.text is not None:
                response_text = response.text
            if reservation is not None:
                assert manager is not None
                response_tokens = manager.count_tokens(
                    response_text, resolved_alias
                )
                manager.token_budget.settle(
                    reservation,
                    _actual_usage(response, input_tokens, response_tokens),
                )
                reservation = None

            if isinstance(response, LLMResponse):
                if return_response_obj:
                    return response
                return response.text if response.text is not None else ""
            return response
        except asyncio.CancelledError as exc:
            if reservation is not None:
                assert manager is not None
                sent = getattr(exc, "request_sent", request_sent) is not False
                if sent:
                    manager.token_budget.settle(
                        reservation,
                        _actual_usage(exc, input_tokens, 0),
                    )
                else:
                    manager.token_budget.release(reservation)
            raise
        except Exception as e:
            if reservation is not None:
                assert manager is not None
                sent = getattr(e, "request_sent", request_sent) is not False
                if sent:
                    manager.token_budget.settle(
                        reservation,
                        _actual_usage(e, input_tokens, 0),
                    )
                else:
                    manager.token_budget.release(reservation)
            if isinstance(e, TokenLimitExceededError):
                raise e
            if isinstance(e, LLMGenerationError):
                raise e
            is_transient = _is_retryable_llm_error(e)

            if attempt == attempts or not is_transient:
                logger.error(
                    "LLM generation failed on attempt %s with error type %s.",
                    attempt,
                    type(e).__name__,
                )
                raise LLMGenerationError(
                    "LLM generation failed after "
                    f"{attempt} attempt(s) with {type(e).__name__}."
                ) from e

            sleep_time = float(backoff_factor) * (2 ** (attempt - 1))
            logger.warning(
                "LLM generation failed (attempt %s/%s) with error type %s; "
                "retrying in %.2fs.",
                attempt,
                attempts,
                type(e).__name__,
                sleep_time,
            )
            if sleep_time:
                await asyncio.sleep(sleep_time)

    raise LLMGenerationError("LLM generation failed: maximum retries exceeded.")
