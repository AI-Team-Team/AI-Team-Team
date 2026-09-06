# Selective Episodic Memory

Selective Episodic Memory is an optional Agent-owned catalog for finding and temporarily recalling prior Agent turns.

It does not replace the append-only System Memory Journal, the bounded Working Context, or the deliberate artifacts stored in a Private Agent DocLib.

The feature is disabled by default because every indexed terminal turn normally adds an isolated model call, bounded failure retries, and durable catalog records.

## Identity and Membership Boundary

A Memory Card belongs to one immutable `agent_id`, never to an AgentTeam membership.

Adding or removing an Agent from an AgentTeam changes only the `team_id ↔ agent_id` relation and does not copy, clear, relabel, or otherwise mutate the Agent's Journal, catalog, Working Context, retained references, model binding, identity fields, invocation lock, lifecycle, or Private DocLib.

A shared Agent can search its own catalog across AgentTeams, while each result retains its original `origin_team_id` and `discussion_id` provenance.

Team ACLs and communication agreements cannot grant another Agent access to an Agent's catalog.

## Three Memory Layers

### System Memory Journal

The System Memory Journal is an append-only host-visible event stream containing sanitized user, assistant, system, and tool-message records together with turn, team, discussion, lifecycle, indexing, search, recall, retention, and forget metadata.

Journal events retain an Agent name snapshot and may survive confirmed permanent Agent deletion, but they are never exposed through Agent tools.

Private DocLib bodies, recalled memory bodies, and tool content without explicit capture consent are replaced by metadata-only records before entering the Journal.

The Journal does not capture or infer hidden model reasoning.

### AI-visible Memory Catalog

When the optional mode is enabled, each completed or incomplete business Agent turn produces one deterministic sanitized `AgentMemorySegment` after the turn ends.

Cancelled turns and turns terminated by framework consistency failures remain visible in the Journal but do not create segments or cards.

The segment's `recall_content` is rendered deterministically from its immutable sanitized source events, and its SHA-256 digest is verified during recall and restore.

An isolated background call to the same Agent model generates only the card title, summary, and normalized tags.

The indexing call uses the Agent invocation lock, receives a detached temporary prompt, does not use tools, does not enter `agent.messages`, and cannot recursively create another memory turn.

Indexing failure never changes the business turn result and leaves a retryable or failed segment visible to trusted host APIs.

### Working Context

`agent.messages` is the persisted bounded model-visible Working Context and may be compressed or pruned.

`agent.message_history` is a compatibility view projected from Agent-owned Journal message events after restore and is not loaded back into `agent.messages`.

This separation prevents a complete historical log from becoming model-visible merely because the manager restarted.

## Enabling the Optional Mode

```python
from ai_team_team import ATTConfig, EpisodicMemoryConfig

config = ATTConfig(
    episodic_memory=EpisodicMemoryConfig(
        enabled=True,
        index_max_retries=2,
        index_retry_backoff_factor=0.5,
        index_worker_count=2,
        max_search_results=20,
        max_recall_lines=100,
        max_recall_chars=20_000,
        max_recall_tokens=4_000,
        max_tags_per_card=12,
        max_retained_context_items=20,
    )
)
```

When `enabled=False`, ATT creates no segments or Memory Cards, performs no label-generation calls, exposes no memory tools, and does not require SQLite FTS5.

The append-only Journal and Working Context separation remain active because they are persistence and audit boundaries rather than AI-visible advanced memory.

Enabling the feature requires SQLite FTS5, and ATT fails clearly when the local SQLite build cannot provide it.

## Agent Tools

The following tools appear in the invocation-scoped tool view only while the feature is enabled:

- `search_memories(query=None, tags=None, team_id=None, discussion_id=None, limit=20, cursor=None)` returns only Agent-owned card metadata and provenance.
- `recall_memory(memory_id, start_line=1, end_line=None)` returns a bounded historical-data observation from one active Agent-owned card.
- `keep_memory_in_context(memory_id, note=None)` retains only a compact reference after the same card was recalled earlier in the current Agent turn.
- `forget_memory(memory_id, reason=None)` hides the card and removes its retained references without modifying Journal events or source records.

Recall content is prefixed as historical reference data rather than instructions.

The recalled body is available only to the current invocation and is replaced in Working Context with `[Historical memory recalled: <memory_id>]` when that invocation ends.

A normal assistant answer derived from a recall remains part of the new business turn because it is new Agent output.

Precise long-term material should be deliberately rewritten into the Agent's Private DocLib with `write_private_file` rather than retained as a large Working Context block.

## Tool Capture Policy

Every `Tool` has a `memory_capture` policy, and the default is `"metadata_only"`.

Only `memory_capture="content"` explicitly permits a tool observation body to enter the Journal and deterministic recall segment.

Private DocLib and episodic-memory tools are always metadata-only, and their transient bodies are never copied automatically into Memory Cards.

## Persistence and Restore

Schema 7 stores Working Context, Journal events, source-linked segments, Memory Cards, normalized tags, retained references, and the FTS5 search index in separate structures.

Full saves never delete Journal rows, while incremental journal updates are insert-only and reject attempts to modify an existing event ID.

Restore validates event and sequence uniqueness, Agent ownership, source-event existence and ordering, turn boundaries, deterministic content and digest, normalized tags, card-to-segment provenance, retained-reference ownership, and FTS5 availability when enabled.

Persisted `processing` index jobs return to `pending` after restore, and `await manager.flush_memory_indexing()` waits for every currently runnable background job.

Trusted hosts can use `retry_memory_index`, `list_memory_index_failures`, `restore_forgotten_memory`, and `list_agent_history` without exposing Journal access to Agents.

Confirmed permanent Agent deletion removes Working Context, segments, cards, retained references, and the Private Agent DocLib while retaining immutable Journal events with historical identity snapshots.
