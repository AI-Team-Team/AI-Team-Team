"""Explicit durable workspaces and immutable source graphs; no model requests."""

import tempfile
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.database.persistence.records import DomainRecord
from ai_team_team.database.persistence.records import thaw
from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient


def make_manager(test, *, volatile=False):
    workspace = tempfile.TemporaryDirectory(prefix="att-phase1-")
    test.addCleanup(workspace.cleanup)
    path = str(Path(workspace.name) / "state.sqlite")
    client = ScriptedModelClient()
    manager = ATTManager(Agent("Root", "Architect", client), ATTConfig(workspace_root=workspace.name),
                         db_path=None if volatile else path, persistence_mode="volatile" if volatile else "durable")
    manager.register_llm_client("fixture", client)
    test.addAsyncCleanup(manager.close)
    return manager, path, client


def record(table, **values):
    from ai_team_team.database.models import ACTIVITY_TABLES
    schema = ACTIVITY_TABLES[table]
    values.setdefault("created_version" if schema.info["append"] else "state_version", 1)
    for column in schema.columns:
        if column.nullable:
            values.setdefault(column.name, None)
    return DomainRecord.capture(table, values)


def invocation_graph(owner):
    return (
        record("activity_admissions", admission_id="admission", agent_id=owner, runtime_generation=1,
               scope_kind="personal", disposition="admitted", accepted_at=1.0),
        record("activity_invocations", invocation_id="invocation", admission_id="admission", agent_id=owner,
               runtime_generation=1, scope_kind="personal", context_version=1, started_at=1.0, interrupted=0),
        record("notification_frames", frame_id="frame", invocation_id="invocation", agent_id=owner,
               context_version=1, arrival_cutoff=0, summary_references=[]),
    )


def model_request(owner):
    return record("model_requests", model_request_id="model-request", frame_id="frame", agent_id=owner,
                  model_alias="fixture", attempt_index=1, input_version=1, dispatch_state="unsent", outcome="pending",
                  created_at=1.0, request_budget=120.0, sequence_budget=600.0)


def hydrate_team_stream_id(manager, team, stream_id):
    """Install an opaque stream identity as if supplied by checkpoint hydration."""
    records = manager._records.snapshot()
    previous = next(row for row in records if row.table_name == "chat_streams" and row.values["team_id"] == team.team_id)
    restored = []
    for row in records:
        if row.table_name in {"chat_streams", "chat_events", "membership_intervals"} and row.values["stream_id"] == previous.values["stream_id"]:
            row = DomainRecord.capture(row.table_name, {**thaw(row.values), "stream_id": stream_id})
        restored.append(row)
    manager._records.restore(restored)


def execution(owner, *, status="queued", version=1):
    return record("executions", execution_id="execution", agent_id=owner, invocation_id="invocation", scope_kind="personal",
                  tool_name="fixture_tool", effects=["read_only"], runtime_generation=1, visibility="foreground",
                  status=status, attention="none", outcome_unconfirmed=0, created_at=1.0, state_version=version)
