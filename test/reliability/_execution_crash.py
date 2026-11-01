"""Abrupt child exits surround real executor and SQLite commit boundaries."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import SuppressionPreference, ToolExecutionContract


class UnusedClient:
    async def generate(self, **kwargs):
        raise AssertionError("The crash fixture cannot request a model.")


async def main(workspace, phase):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    manager = ATTManager(Agent("CrashOwner", "Researcher", UnusedClient()),
        ATTConfig(workspace_root=str(workspace)), db_path=str(workspace / "state.sqlite"))
    manager.register_llm_client("fixture", manager.root_ai.llm_client)
    await manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=manager.root_ai)
    await manager.save_state()

    async def operation():
        with (workspace / "effects.log").open("a", encoding="utf-8") as stream:
            stream.write("dispatched\n")
            stream.flush()
            os.fsync(stream.fileno())
        if phase == "after_dispatch":
            os._exit(73)
        return "Committed synthetic result"

    manager.register_tool("operation", func=operation,
        execution_contract=ToolExecutionContract(effects=("domain_mutation",), background_allowed=True,
            required_scope="personal", mutation_safety="trusted_host"),
        resource_resolver=lambda scope, arguments: ())
    if phase == "before_dispatch":
        manager._executions.enqueue = lambda job: None
    if phase == "after_result_observation":
        async def returned(job, result):
            os._exit(73)
        manager._executions.finish_result = returned
    if phase == "before_result_commit":
        def commit(connection):
            database = connection.engine.url.database
            if not database or Path(database).resolve() != (workspace / "state.sqlite").resolve():
                return
            row = connection.exec_driver_sql("SELECT COUNT(*) FROM executions WHERE tool_name='operation' AND status='completed'").scalar()
            if row:
                os._exit(73)
        event.listen(Engine, "commit", commit)
    if phase == "after_result_commit":
        def scheduled(notice_id):
            notice = manager._records.index[("agent_notifications", (notice_id,))]
            if notice.values["source_kind"] == "execution" and notice.values["deduplication_key"].endswith(":terminal"):
                os._exit(73)
        manager._activity.schedule_notice = scheduled
    await manager.start_background_task("operation", {}, actor=manager.root_ai)
    if phase == "before_dispatch":
        os._exit(73)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
