import asyncio
import logging
from typing import Union, List, Dict, Optional, Any
from .exceptions import LLMGenerationError, TokenLimitExceededError

logger = logging.getLogger("ATT.CoreUtils")

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
    import json

    prompt_tokens = 0
    current_usage = 0
    resolved_alias = model_alias
    
    if manager:
        resolved_alias = resolved_alias or manager.resolve_model_alias(llm_client)
        limit = manager.config.model_token_limits.get(resolved_alias)
        if limit is not None:
            prompt_text = prompt if isinstance(prompt, str) else json.dumps(prompt)
            prompt_tokens = manager.count_tokens(prompt_text, resolved_alias)
            current_usage = manager.model_token_usage.setdefault(resolved_alias, 0)
            if current_usage + prompt_tokens > limit:
                if getattr(manager, "on_system_event", None):
                    try:
                        manager.on_system_event("token_limit_exceeded", {
                            "model_name": resolved_alias,
                            "limit": limit,
                            "current_usage": current_usage,
                            "required_tokens": prompt_tokens
                        })
                    except Exception:
                        pass
                raise TokenLimitExceededError(
                    f"Model {resolved_alias} token limit exceeded. Budget: {limit}, Current usage: {current_usage}, Needed: {prompt_tokens}"
                )

    for attempt in range(1, retries + 1):
        try:
            if hasattr(llm_client, "generate"):
                kwargs = {}
                if tools is not None:
                    try:
                        import inspect
                        sig = inspect.signature(llm_client.generate)
                        if any(p.name == "tools" or p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                            kwargs["tools"] = tools
                    except Exception:
                        import unittest.mock
                        if isinstance(llm_client, unittest.mock.NonCallableMock) or isinstance(llm_client.generate, unittest.mock.NonCallableMock):
                            kwargs["tools"] = tools
                response = await llm_client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    require_json=require_json,
                    **kwargs
                )
            else:
                # Fallback to direct callable
                if asyncio.iscoroutinefunction(llm_client):
                    response = await llm_client(
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                        require_json=require_json
                    )
                else:
                    response = llm_client(
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                        require_json=require_json
                    )
            
            # Post-flight token consumption update
            if manager and resolved_alias in manager.config.model_token_limits:
                response_text = ""
                if isinstance(response, str):
                    response_text = response
                elif isinstance(response, LLMResponse) and response.text is not None:
                    response_text = response.text
                elif hasattr(response, "text") and response.text is not None:
                    response_text = response.text
                
                response_tokens = manager.count_tokens(response_text, resolved_alias)
                manager.model_token_usage[resolved_alias] = current_usage + prompt_tokens + response_tokens

            if isinstance(response, LLMResponse):
                if return_response_obj:
                    return response
                return response.text if response.text is not None else ""
            return response
        except Exception as e:
            if isinstance(e, TokenLimitExceededError):
                raise e
            err_msg = str(e)
            is_transient = any(
                term in err_msg.lower()
                for term in ["rate limit", "timeout", "503", "500", "transient", "overloaded"]
            )
            
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
