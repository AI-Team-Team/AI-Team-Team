"""Concrete ordinary, audit, and optional-index request reference fixtures."""

from ai_team_team.core.memory import AgentMemorySegment, MemoryIndexStatus
from ai_team_team.core.memory.sanitization import content_digest, render_recall_content

from ._support import invocation_graph, model_request, record
from .test_audit_and_quota import audit_records, audit_request


def request_profiles(owner):
    return (
        model_request(owner),
        audit_request(),
        record("memory_index_requests", request_id="index-request", segment_id="index-segment",
               beneficiary_agent_id=owner, source_version=1, model_alias="fixture", attempt_index=1,
               dispatch_state="unsent", outcome="pending", input_digest=content_digest("fixture"), created_at=1.0),
    )


async def install_request_sources(manager):
    owner = manager.root_ai.agent_id
    await manager._records.commit((*invocation_graph(owner), *audit_records(owner)))
    events = [manager._memory.record_event(kind, agent=manager.root_ai, invocation_id="invocation",
                                          payload=payload, persist=False, inherit_context=False)
              for kind, payload in (
                  ("activity_invocation_started", {}),
                  ("message", {"content": "Fixture conclusion"}),
                  ("activity_invocation_finished", {"intent": "idle"}),
              )]
    content = render_recall_content(events)
    manager._memory.segments["index-segment"] = AgentMemorySegment(
        segment_id="index-segment", agent_id=owner, invocation_id="invocation",
        source_event_ids=[event.event_id for event in events], recall_content=content,
        content_sha256=content_digest(content), status=MemoryIndexStatus.FAILED,
        attempts=1, last_error_kind="fixture", created_at=1.0, updated_at=1.0,
    )
