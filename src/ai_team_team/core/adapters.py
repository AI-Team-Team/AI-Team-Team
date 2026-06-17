from typing import Union, List, Dict, Optional, Any, Callable

class HandlerClientAdapter:
    """Wraps a global generator handler callback to conform to LLMClientProto."""
    def __init__(self, model_name: str, handler: Callable[..., str]):
        self.model_name = model_name
        self.handler = handler

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> str:
        return await self.handler(
            model_name=self.model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            require_json=require_json
        )

class ManagerCriticClientAdapter:
    """Wraps the manager's critic client and global generator handler callback."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> str:
        if self.manager.critic_client:
            return await self.manager.critic_client.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                require_json=require_json
            )
        if self.manager.generator_handler:
            return await self.manager.generator_handler(
                model_name="critic",
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                require_json=require_json
            )
        raise ValueError("No critic client or generator handler configured on ATTManager.")
