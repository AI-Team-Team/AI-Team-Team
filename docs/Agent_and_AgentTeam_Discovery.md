# Agent and AgentTeam Discovery

ATT lets Agents discover people and organizations on demand without submitting the entire organization directory to every model invocation or selecting collaborators for them.

Ordinary Text ReAct, Native, personal-inbox, and governance interactions preserve the Agent's own identity, instructions, memory, current AgentTeam context, applicable rules, and available tools.

Team-formation deliberation uses the same discovery tools rather than injecting a separate global candidate directory.

## Public APIs and Tools

The manager provides synchronous, read-only APIs:

```python
page = manager.list_entities(entity_type="all", start_index=1)
matches = manager.search_entities(
    keywords=["database", "research"],
    entity_type="agent",
    start_index=21,
    end_index=40,
)
person = manager.inspect_entity(entity_type="agent", entity_id=agent.agent_id)
organization = manager.inspect_entity(entity_type="agent_team", entity_id=team.team_id)
```

`list_entities()` and `search_entities()` accept `entity_type="agent"`, `"agent_team"`, or `"all"`.

`inspect_entity()` accepts only `"agent"` or `"agent_team"` and requires the corresponding stable ID.

The three built-in Agent tools have the same names and arguments and return JSON observations.

They require an active, registered ordinary Agent invocation but do not require an AgentTeam membership or accept an acting-Agent override.

They remain available when dynamic delegation or optional episodic memory is disabled, and reaching the delegation depth limit does not hide them.

Python APIs return `EntityDiscoveryResult` pages or an `AgentDirectoryRecord` / `AgentTeamDirectoryRecord` for inspection.

Invalid arguments raise a validation error derived from `ValueError`; Agent tools classify them as `invalid_arguments`.

Inspection of an unknown or ineligible ID raises `KeyError`; the tool returns a `business_error` without disclosing whether the ID belongs to an excluded identity.

## Directory Fields and Privacy

| Entity | Public directory fields | Ordering label |
| --- | --- | --- |
| Agent | `agent_id`, `name`, `role`, `role_description` | `name` |
| AgentTeam | `team_id`, `team_purpose`, `team_progress`, `parent_team_id`, `depth` | `team_id` |

Each record also carries an `entity_type` discriminator, which is not a searchable field.

A top-level AgentTeam has `parent_team_id=null` and `depth=1`.

Depth is derived from the current topology without updating runtime depth caches.

Discovery does not expose system instructions, model bindings, inboxes, member lists, private files, personal message history, memory catalogs, tool arguments, or hidden reasoning.

A query does not modify Agent-owned fields, membership relationships, topology, DocLib permissions, or persistent state.

Explicit discovery observations may enter the calling Agent's ordinary history, just like other permitted tool observations.

Removing automatic directory injection does not erase information an Agent already learned through earlier work or explicit reads.

## Discovery Scope and Authority

All active ordinary Agents are eligible, including Root, the caller, idle or currently executing Agents, Agents without memberships, and Agents in an invocation dependency chain.

Retained inactive, archived inactive, deleted, and audit-scoped supervisory Agents are excluded.

Ordinary AgentTeams are discoverable across all topology branches; managed supervisory AgentTeams are excluded.

AgentTeam discovery is independent of whether its DocLib is publicly visible.

Discovery never grants membership consent, immediate invocation availability, a communication Agreement, or access to documents.

Formation, admission, communication, and file tools independently revalidate current consent, dependency, lifecycle, topology, and ACL conditions when an action is attempted.

The trusted host's registries and `manager.render_topology_tree()` remain available for diagnostics, but their full contents are not automatically submitted to Agents.

## Position Ranges and Result Metadata

Positions count entities rather than physical text lines and are one-based with inclusive endpoints.

`start_index` defaults to `1`; omitting `end_index` requests up to 30 entities starting at the requested start.

For example, `start_index=21` requests positions 21 through 50.

Thirty is a default count, not a hard limit on an explicit range or a guaranteed token budget.

Both supplied positions must be strict positive integers; booleans, fractions, zero, negative values, and an end preceding the start are invalid.

Filtering and ordering occur before pagination, and mixed results use one combined sequence.

The page reports `requested_start_index`, `requested_end_index`, `actual_start_index`, `actual_end_index`, `maximum_index`, `total_results`, `returned_count`, and `items`.

When the end is omitted, `requested_end_index` records the effective default endpoint rather than `null`.

An end beyond the available results returns the remaining records and their actual positions.

A start beyond the available results returns an empty page with both actual positions set to `null`.

`maximum_index` equals `total_results` and is `0` for an empty selected result set, although `0` remains invalid as an input position.

## Ordering and Keyword Matching

Listing and searching share deterministic alphabetical ordering using Unicode case-folded labels, with uppercase preceding lowercase for otherwise case-equivalent labels.

For example, `A, a, B, b` is the ordering rather than `A, B, a, b`.

Original labels, entity type, and stable ID resolve remaining ties instead of registration order.

Ordering does not introduce locale-specific, phonetic, natural-number, or relevance ranking.

Search requires a nonempty list of strings and rejects every empty or whitespace-only keyword.

Keywords are trimmed and case-folded, and matching uses ordinary case-insensitive substrings across the public directory fields.

Multiple keywords use OR semantics, and an entity matching several keywords appears only once.

There are no regular expressions, query operators, implicit collaborator preferences, or private-content searches.

## Live Queries and Persistence

Each call captures detached public values without awaiting, borrowing Agent invocation locks, or sending live runtime objects to a background worker.

Synchronous host queries, including queries made by background observational callbacks, share a publication lock with Agent registration, lifecycle changes, team status and topology updates, and state restoration.

Team creation and restore rollbacks finish under that same lock, so a query cannot observe their partially published registries.

This protects read-only discovery against framework-managed changes; it does not make arbitrary host mutations of registries or runtime objects thread-safe.

Its filtering, ordering, counts, records, and range metadata all describe that captured directory.

Separate calls read the live directory independently, so consecutive pages may repeat or omit positions when people or organizations change between calls.

Use stable IDs for inspection and subsequent operations rather than treating result positions as permanent identities.

There is no required directory version, persisted pagination snapshot, or separate discovery index.

Existing persisted Agent and AgentTeam fields remain authoritative, so discovery works immediately after restore and schema remains `11`.

## Deferred Extensions

Cursor pagination remains a future design direction and has no public argument, configuration switch, placeholder tool, or dormant implementation.

Vector discovery is also deferred until an explicit vector-model integration design exists.

Any future extension must retain the same discovery scope, stable identities, permitted directory fields, and independent authorization boundaries.
