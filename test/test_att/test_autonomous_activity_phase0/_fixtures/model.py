"""Real protocol-shaped model clients with scripted gates and captured frames."""

import copy
from collections import deque
from dataclasses import dataclass
from typing import Any

from ai_team_team import LLMResponse
from ai_team_team.tool import Tool

from .barriers import AsyncBarrier


@dataclass(frozen=True)
class ModelStep:
    response: LLMResponse | str | BaseException
    barrier: AsyncBarrier | None = None


@dataclass(frozen=True)
class CapturedRequest:
    prompt: Any
    system_instruction: str | None
    tools: tuple[Tool, ...]
    require_json: bool
    max_output_tokens: int | None


class ScriptedModelClient:
    def __init__(self, *steps: ModelStep, native: bool = True):
        self.steps = deque(steps)
        self.native = native
        self.requests: list[CapturedRequest] = []
        self.unexpected_requests = 0
        self.in_flight = 0
        self.maximum_in_flight = 0

    def supports_native_tool_calling(self) -> bool:
        return self.native

    def supports_output_token_limit(self) -> bool:
        return True

    async def generate(
        self,
        prompt=None,
        system_instruction=None,
        tools: list[Tool] | None = None,
        max_output_tokens: int | None = None,
        temperature=0.7,
        require_json=False,
    ) -> LLMResponse:
        if tools is not None and any(not isinstance(tool, Tool) for tool in tools):
            raise AssertionError("The provider-neutral contract requires Tool objects.")
        self.requests.append(
            CapturedRequest(
                copy.deepcopy(prompt),
                system_instruction,
                tuple(tools or ()),
                require_json,
                max_output_tokens,
            )
        )
        if not self.steps:
            self.unexpected_requests += 1
            raise AssertionError("The model received an unscripted request.")
        step = self.steps.popleft()
        self.in_flight += 1
        self.maximum_in_flight = max(self.maximum_in_flight, self.in_flight)
        try:
            if step.barrier is not None:
                await step.barrier.pause()
            if isinstance(step.response, BaseException):
                raise step.response
            return (
                LLMResponse(text=step.response) if isinstance(step.response, str) else step.response
            )
        finally:
            self.in_flight -= 1
