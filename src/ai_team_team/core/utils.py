import asyncio
import inspect
import json
import logging
from typing import Union, List, Dict, Optional, Any
from .exceptions import LLMGenerationError, TokenLimitExceededError

logger = logging.getLogger("ATT.CoreUtils")


def _output_limit_parameter(llm_client: Any) -> Optional[str]:
    support_check = getattr(llm_client, "supports_output_token_limit", None)
    if callable(support_check):
        try:
            supported = support_check()
            if supported in {"max_output_tokens", "max_tokens"}:
                return supported
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

async def generate_with_retry(
    llm_client: Any,
    prompt: Union[str, List[Dict[str, str]]],
    system_instruction: Optional[str] = None,
    temperature: float = 0.3,
    require_json: bool = False,
    retries: int = 3,
    backoff_factor: float = 1.5,
    tools: Optional[List[Dict[str, Any]]] = None,
    return_response_obj: bool = False,
    manager: Optional[Any] = None,
    model_alias: Optional[str] = None
) -> Union[str, Any]:
    """Invokes LLM client generation with exponential backoff on transient errors."""
    from .response import LLMResponse
    prompt_tokens = 0
    resolved_alias = model_alias
    prompt_text = prompt if isinstance(prompt, str) else json.dumps(prompt)

    if manager:
        resolved_alias = resolved_alias or manager.resolve_model_alias(llm_client)
        prompt_tokens = manager.count_tokens(prompt_text, resolved_alias)

    for attempt in range(1, retries + 1):
        reservation = None
        request_sent = False
        try:
            output_parameter = None
            if (
                manager
                and resolved_alias in manager.config.model_token_limits
            ):
                output_parameter = _output_limit_parameter(llm_client)
                requested_output = (
                    _configured_output_limit(manager, resolved_alias)
                    if output_parameter
                    else None
                )
                reservation = manager.token_budget.reserve(
                    resolved_alias,
                    prompt_tokens,
                    requested_output,
                )

            if hasattr(llm_client, "generate"):
                kwargs = {}
                if tools is not None:
                    try:
                        sig = inspect.signature(llm_client.generate)
                        if any(p.name == "tools" or p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                            kwargs["tools"] = tools
                    except Exception:
                        pass
                if output_parameter and reservation is not None:
                    kwargs[output_parameter] = reservation.output_tokens
                request_sent = True
                response = await llm_client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    require_json=require_json,
                    **kwargs
                )
            else:
                # Fallback to direct callable
                call_kwargs = {
                    "prompt": prompt,
                    "system_instruction": system_instruction,
                    "temperature": temperature,
                    "require_json": require_json,
                }
                if output_parameter and reservation is not None:
                    call_kwargs[output_parameter] = reservation.output_tokens
                request_sent = True
                if asyncio.iscoroutinefunction(llm_client):
                    response = await llm_client(**call_kwargs)
                else:
                    response = llm_client(**call_kwargs)
            
            response_text = ""
            if isinstance(response, str):
                response_text = response
            elif isinstance(response, LLMResponse) and response.text is not None:
                response_text = response.text
            elif hasattr(response, "text") and response.text is not None:
                response_text = response.text
            response_tokens = (
                manager.count_tokens(response_text, resolved_alias)
                if manager
                else 0
            )
            if reservation is not None:
                manager.token_budget.settle(
                    reservation,
                    _actual_usage(response, prompt_tokens, response_tokens),
                )
                reservation = None

            if isinstance(response, LLMResponse):
                if return_response_obj:
                    return response
                return response.text if response.text is not None else ""
            return response
        except asyncio.CancelledError as exc:
            if reservation is not None:
                sent = getattr(exc, "request_sent", request_sent) is not False
                manager.token_budget.settle(
                    reservation,
                    _actual_usage(
                        exc,
                        prompt_tokens if sent else 0,
                        0,
                    ),
                )
            raise
        except Exception as e:
            if reservation is not None:
                sent = getattr(e, "request_sent", request_sent) is not False
                manager.token_budget.settle(
                    reservation,
                    _actual_usage(
                        e,
                        prompt_tokens if sent else 0,
                        0,
                    ),
                )
            if isinstance(e, TokenLimitExceededError):
                raise e
            err_msg = str(e)
            is_permanent = any(
                term in err_msg.lower()
                for term in ["invalid api key", "unauthorized", "not found"]
            )
            is_transient = not is_permanent
            
            if attempt == retries or not is_transient:
                logger.error(f"LLM generation failed permanently on attempt {attempt}: {e}")
                raise LLMGenerationError(f"LLM generation failed after {attempt} attempts: {e}")
                
            sleep_time = backoff_factor ** attempt
            logger.warning(
                f"LLM generation failed (attempt {attempt}/{retries}): {e}. "
                f"Retrying in {sleep_time:.2f}s..."
            )
            await asyncio.sleep(sleep_time)

    raise LLMGenerationError("LLM generation failed: maximum retries exceeded.")
