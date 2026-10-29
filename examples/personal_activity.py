"""Run a deterministic personal interaction and restore the same identity offline."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse, Tool, ToolCall


class DemoClient:
    """A scripted provider for contract examples, not a business reasoning model."""

    def __init__(self, native: bool = True, *, answer: bool = True):
        self.native = native
        self.answer = answer
        self.calls = 0

    def supports_native_tool_calling(self) -> bool:
        return self.native

    def supports_output_token_limit(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str | list[dict[str, Any]],
        system_instruction: str | None = None,
        tools: list[Tool] | None = None,
        max_output_tokens: int | None = None,
        temperature: float = 0.7,
        require_json: bool = False,
    ) -> LLMResponse:
        self.calls += 1
        if require_json:
            raise ValueError("This demo does not provide optional memory-indexing responses.")
        if self.answer and self.calls == 1:
            return LLMResponse(text="Final Answer: The demo received its instruction.")
        if self.native:
            return LLMResponse(tool_calls=[
                ToolCall(f"idle-{self.calls}", "set_activity_intent", {"intent": {"kind": "idle"}})
            ])
        return LLMResponse(text="Action: set_activity_intent(intent={'kind': 'idle'})")


async def run_demo(workspace: Path, *, native: bool = True) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    state = workspace / "personal.sqlite"
    client = DemoClient(native)
    config = ATTConfig(workspace_root=str(workspace), tool_calling_mode="auto")
    root = Agent("Root", "Coordinator", client)
    async with ATTManager(root, config, db_path=str(state)) as manager:
        manager.register_llm_client("demo", client)
        admission = await manager.activate_agent(root.agent_id)
        checkpoint = await manager.wait_for_activity_checkpoint(admission.admission_id, intent="idle")
        owner_id = root.agent_id
        await manager.save_state()

    restored_client = DemoClient(native, answer=False)
    async with ATTManager(
        Agent("RestoreHost", "Coordinator", restored_client),
        ATTConfig(workspace_root=str(workspace)),
        db_path=str(state),
    ) as manager:
        manager.register_llm_client("demo", restored_client)
        await manager.load_state(str(state))
        current_root = manager.root_ai
        assert current_root.agent_id == owner_id
        assert current_root is not root
        assert manager.inspect_agent_activity(owner_id).intent == "idle"
        assert restored_client.calls == 0
    return {"intent": checkpoint.intent, "model_calls": client.calls,
            "same_identity_restored": True, "durability": admission.durability}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="store_true", help="Use Text ReAct instead of Native tools.")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="att-personal-example-") as directory:
        result = asyncio.run(run_demo(Path(directory), native=not options.text))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
