"""Inspect an owner-authorized background result without a network provider."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import SuppressionPreference, ToolExecutionContract
from personal_activity import DemoClient


async def run_demo(workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    client = DemoClient(answer=False)
    owner = Agent("Owner", "Researcher", client)
    async with ATTManager(owner, ATTConfig(workspace_root=str(workspace)),
                          db_path=str(workspace / "tasks.sqlite")) as manager:
        manager.register_llm_client("demo", client)
        # This Host-controlled demo inspects results explicitly instead of
        # waking the owner for ordinary task reminders. Delivery still occurs.
        await manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=owner)
        committed = asyncio.Event()

        async def observe(event: str, metadata: dict[str, Any]) -> None:
            if event == "execution_outcome_committed":
                committed.set()

        manager.on_system_event = observe

        async def count_records() -> str:
            return "The example counted 7 records."

        manager.register_tool(
            count_records,
            execution_contract=ToolExecutionContract(
                effects=("read_only",), background_allowed=True, required_scope="personal",
            ),
            resource_resolver=lambda scope, arguments: (),
        )
        handle = await manager.start_background_task("count_records", {}, actor=owner)
        # This is an observer deadline, not a persistence flush timeout.
        async with asyncio.timeout(30):
            await committed.wait()
        view = manager.inspect_background_task(handle.execution_id, actor=owner)
        result = await manager.read_background_task_result(handle.execution_id, actor=owner)
        assert view.execution_state == "completed"
        assert view.attention_state == "required"
        assert "7 records" in result.content
        assert manager.inspect_background_task(handle.execution_id, actor=owner).attention_state == "required"
        acknowledged = await manager.acknowledge_background_task(handle.execution_id, actor=owner)
        assert client.calls == 0
        await manager.save_state()
    return {"admission": handle.status, "execution": view.execution_state,
            "attention": acknowledged.status, "durability": handle.durability}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="att-task-example-") as directory:
        result = asyncio.run(run_demo(Path(directory)))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
