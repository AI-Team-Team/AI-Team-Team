import asyncio
import logging
from typing import Union, List, Dict, Optional, Any
from .exceptions import LLMGenerationError

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
    return_response_obj: bool = False
) -> Union[str, Any]:
    """Invokes LLM client generation with exponential backoff on transient errors."""
    from .response import LLMResponse
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
            
            if isinstance(response, LLMResponse):
                if return_response_obj:
                    return response
                return response.text if response.text is not None else ""
            return response
        except Exception as e:
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
