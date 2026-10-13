"""Concrete chat evidence graphs, without running the later chat runtime."""

from ai_team_team import Agent
from ai_team_team.database.persistence.records import DomainRecord, thaw

from ._support import invocation_graph, record


async def install_chat(manager, *, kind="direct"):
    if kind == "team":
        team = manager.create_agent_team(manager.root_ai, member_configs={
            f"ChatMember-{index}": {"model": "fixture"} for index in range(4)
        })
        author, recipient = team.members[:2]
        stream = next(row for row in manager._records.snapshot() if row.table_name == "chat_streams" and row.values["team_id"] == team.team_id)
        prerequisites = ()
    else:
        team = None
        author = manager.root_ai
        recipient = manager.register_agent(Agent("Recipient", "Researcher", author.llm_client))
        left, right = sorted((author.agent_id, recipient.agent_id))
        prerequisites = (record("direct_relationships", relationship_id="relationship", agent_a_id=left, agent_b_id=right,
                                friendship=1, blocked_a=0, blocked_b=0, refused_a=0, refused_b=0,
                                generation=1, allowance_a=3, allowance_b=3),)
        stream = record("chat_streams", stream_id="direct-stream", relationship_id="relationship", next_position=1)
    await manager.save_state()
    position = stream.values["next_position"]
    values = {**thaw(stream.values), "next_position": position + 1, "state_version": stream.version + 1}
    await manager._records.commit((*invocation_graph(author.agent_id), *prerequisites,
        DomainRecord.capture("chat_streams", values),
        record("chat_events", event_id="send-event", stream_id=stream.values["stream_id"], sequence=position,
               event_kind="send", actor_agent_id=author.agent_id, created_at=2.0),
        record("chat_messages", message_id="message", stream_id=stream.values["stream_id"], author_agent_id=author.agent_id,
               publication_event_id="send-event", invocation_id="invocation", operation_key="send-operation", created_at=2.0),
        record("chat_revisions", revision_id="revision", message_id="message", event_id="send-event", revision_number=1,
               markdown="Fixture message", title="Fixture title", committed_at=2.0),
        record("chat_message_projections", message_id="message", revision_id="revision")))
    return team, author, recipient


def withdrawal_delta(manager, *, include_projection=True):
    message = manager._records.index[("chat_messages", ("message",))]
    stream = manager._records.index[("chat_streams", (message.values["stream_id"],))]
    projection = manager._records.index[("chat_message_projections", ("message",))]
    records = [
        DomainRecord.capture("chat_streams", {**thaw(stream.values), "next_position": stream.values["next_position"] + 1, "state_version": stream.version + 1}),
        record("chat_events", event_id="withdraw-event", stream_id=stream.values["stream_id"], sequence=stream.values["next_position"],
               event_kind="withdraw", actor_agent_id=message.values["author_agent_id"], created_at=3.0),
        record("chat_withdrawals", withdrawal_id="withdrawal", message_id="message", revision_id="revision",
               actor_agent_id=message.values["author_agent_id"], event_id="withdraw-event", window_seconds=600.0, committed_at=3.0),
    ]
    if include_projection:
        records.append(DomainRecord.capture("chat_message_projections", {**thaw(projection.values), "withdrawal_id": "withdrawal", "state_version": projection.version + 1}))
    return tuple(records)
