"""Value-only authority rules shared by full SQL and incremental validation."""

from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from sqlalchemy import select

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, Base
from ai_team_team.database.persistence.records import valid_request_outcome
from .chat_operations import validate_chat_operations
from .executions import validate_executions


SOURCE_COLUMNS = {
    "agents": ("agent_id",),
    "libraries": ("lib_id", "library_kind", "owner_team_id", "owner_agent_id"),
    "teams": ("team_id", "lifecycle_state", "parent_team_id", "parent_agent_id"),
    "team_members": ("team_id", "agent_id", "interval_id"),
    "agent_messages": ("agent_id", "invocation_id", "source_execution_id", "source_chat_message_id"),
    "agent_memory_segments": ("segment_id", "agent_id", "invocation_id"),
    "agent_memory_cards": ("agent_id", "invocation_id", "segment_id"),
    "agent_inbox": ("message_id", "agent_id"),
    "system_memory_events": ("event_id", "agent_id"),
    "governance_cases": ("case_id", "principal_agent_id", "principal_team_id"),
}


@dataclass(frozen=True)
class ValidationGraph:
    """Worker-owned, read-only COW projections; no runtime objects or file bodies."""

    records: Mapping[str, tuple[Mapping[str, Any], ...]]
    sources: Mapping[str, tuple[Mapping[str, Any], ...]]


def immutable_rows(rows):
    # JSON values belong exclusively to this detached projection. Rules never
    # mutate them; replacement uses a new table tuple, not a shared live row.
    return tuple(MappingProxyType(dict(row)) for row in rows)


def read_graph(session, *, previous=None, changed_tables=None):
    """Refresh affected table projections from actual transactional SQL values."""
    changed = set(ACTIVITY_TABLES) | set(SOURCE_COLUMNS) if changed_tables is None else changed_tables
    records = dict(previous.records) if previous is not None else {}
    sources = dict(previous.sources) if previous is not None else {}
    for name, table in ACTIVITY_TABLES.items():
        if name in changed or name not in records:
            records[name] = immutable_rows(session.execute(select(table)).mappings())
    for name, columns in SOURCE_COLUMNS.items():
        if name in changed or name not in sources:
            table = Base.metadata.tables[name]
            sources[name] = immutable_rows(session.execute(select(*(table.c[column] for column in columns))).mappings())
    return ValidationGraph(MappingProxyType(records), MappingProxyType(sources))


def validate_graph(graph, *, current_memberships=None, partial_memberships=False):
    """Recheck relational semantics, including reverse and collection dependencies.

    SQL retrieval and physical checks are incremental; these value-only rules
    deliberately retain conservative whole-group checks until a narrower
    dependency can be proved equivalent to the full reference validator.
    """
    rows, sources = graph.records, graph.sources
    indexes = {name: {tuple(row[column.name] for column in table.primary_key): row for row in rows[name]}
               for name, table in ACTIVITY_TABLES.items()}

    def require(condition, reason):
        if not condition:
            raise StateRestoreError(f"Invalid durable checkpoint: {reason}.")

    def get(name, *key):
        row = indexes[name].get(tuple(key))
        require(row is not None, f"missing {name} reference")
        return row


    source_indexes = {
        name: {row[columns[0]]: row for row in sources[name]}
        for name, columns in SOURCE_COLUMNS.items()
        if name not in {"team_members", "agent_messages", "agent_memory_cards"}
    }

    def source(name, key):
        row = source_indexes[name].get(key)
        require(row is not None, f"missing {name} reference")
        return row

    for team in sources["teams"]:
        if team["lifecycle_state"] == "active" and team["parent_team_id"] is not None:
            require(source("teams", team["parent_team_id"])["lifecycle_state"] == "active", "a current AgentTeam parent cannot be dissolved")
    for row in rows["activity_admissions"]:
        if row["scope_kind"] == "agent_team":
            require(any(interval["team_id"] == row["scope_team_id"] and interval["agent_id"] == row["agent_id"]
                        for interval in rows["membership_intervals"]), "admission scope has no membership evidence")
    for row in rows["activity_invocations"]:
        admission = get("activity_admissions", row["admission_id"])
        require(row["agent_id"] == admission["agent_id"], "invocation owner mismatch")
        require(row["runtime_generation"] == admission["runtime_generation"], "invocation generation mismatch")
        if row["scope_kind"] == "agent_team":
            require(any(interval["team_id"] == row["scope_team_id"] and interval["agent_id"] == row["agent_id"]
                        for interval in rows["membership_intervals"]), "invocation scope has no membership evidence")
        # Admissions retain the initially requested scope; a later bounded
        # invocation can capture a deliberately changed scope without rewriting
        # historical authority. Live authority is checked by the admitting service.
        require(row["started_at"] >= admission["accepted_at"] and (row["boundary_at"] is None or row["boundary_at"] >= row["started_at"]), "invocation boundary precedes admission")
    for row in rows["agent_activities"]:
        if row["admission_id"] is not None:
            admission = get("activity_admissions", row["admission_id"])
            require(admission["agent_id"] == row["agent_id"], "activity admission owner mismatch")
    for row in rows["notification_frames"]:
        invocation = get("activity_invocations", row["invocation_id"])
        require(row["agent_id"] == invocation["agent_id"], "frame owner mismatch")
        require(row["context_version"] >= invocation["context_version"], "frame context precedes invocation")
        require(type(row["summary_references"]) is list, "frame summaries require a reference list")
    for row in rows["model_requests"]:
        frame = get("notification_frames", row["frame_id"])
        require(row["agent_id"] == frame["agent_id"], "model request owner mismatch")
        require(row["input_version"] == frame["context_version"], "model request context version mismatch")
    for name in ("model_requests", "audit_model_requests", "memory_index_requests"):
        for row in rows[name]:
            require(row["dispatched_at"] is None or (row["dispatch_state"] in {"sent", "unknown_sent"} and row["dispatched_at"] >= row["created_at"]), "request dispatch timestamp mismatch")
            require(valid_request_outcome(row["dispatch_state"], row["outcome"]), "request dispatch/outcome combination is impossible")
    for row in rows["model_token_claims"]:
        name, key = next((name, row[field]) for name, field in (
            ("model_requests", "model_request_id"), ("audit_model_requests", "audit_request_id"),
            ("memory_index_requests", "index_request_id")) if row[field] is not None)
        require(get(name, key)["model_alias"] == row["model_alias"], "token claim model alias mismatch")
        request = get(name, key)
        if row["settlement"] in {"unknown_sent", "confirmed_unsent"}:
            require(request["dispatch_state"] == row["settlement"], "token settlement dispatch mismatch")
        if row["settlement"] == "known_usage":
            require(request["dispatch_state"] == "sent" and request["outcome"] != "pending", "known usage has no settled sent request")
    for row in rows["memory_index_requests"]:
        owner = source("agent_memory_segments", row["segment_id"])["agent_id"]
        require(owner == row["beneficiary_agent_id"], "index request beneficiary mismatch")

    for row in rows["friendship_requests"]:
        relation = get("direct_relationships", row["relationship_id"])
        require({row["sender_agent_id"], row["recipient_agent_id"]} == {relation["agent_a_id"], relation["agent_b_id"]}, "friendship endpoint mismatch")
        require(row["generation"] <= relation["generation"], "friendship request future generation")
        require((row["status"] == "pending") == (row["responded_at"] is None), "friendship response timestamp mismatch")
        # An accepted older request is historical consent, not current authority.
    for row in rows["direct_relationships"]:
        if row["friendship"]:
            require(not row["blocked_a"] and not row["blocked_b"], "friendship cannot survive an effective block")
            require(any(request["relationship_id"] == row["relationship_id"] and request["generation"] == row["generation"]
                        and request["status"] == "accepted" for request in rows["friendship_requests"]), "friendship has no current consent")
    validate_chat_operations(rows, get, require)
    events = {row["event_id"]: row for row in rows["chat_events"]}
    for row in rows["chat_streams"]:
        positions = [event["sequence"] for event in rows["chat_events"] if event["stream_id"] == row["stream_id"]]
        require(not positions or row["next_position"] > max(positions), "stream ordering cursor mismatch")
        if row["team_id"]:
            dissolved = [event for event in rows["chat_events"] if event["stream_id"] == row["stream_id"] and event["event_kind"] == "dissolve"]
            require(len(dissolved) <= 1 and (not dissolved or dissolved[0]["sequence"] == max(positions)), "dissolved stream has later shared events")
            require((source("teams", row["team_id"])["lifecycle_state"] == "dissolved") == bool(dissolved), "dissolution source projection mismatch")
    intervals = {}
    for row in rows["membership_intervals"]:
        stream = get("chat_streams", row["stream_id"])
        join = events[row["join_event_id"]]
        leave = events.get(row["leave_event_id"])
        require(stream["team_id"] == row["team_id"], "membership stream mismatch")
        require(join["stream_id"] == row["stream_id"] and join["event_kind"] == "join" and join["actor_agent_id"] == row["agent_id"], "membership join mismatch")
        if leave is not None:
            require(leave["stream_id"] == row["stream_id"] and leave["event_kind"] in ("leave", "dissolve") and leave["sequence"] > join["sequence"], "membership leave mismatch")
            require(leave["event_kind"] != "leave" or leave["actor_agent_id"] == row["agent_id"], "membership leave owner mismatch")
        intervals.setdefault((row["team_id"], row["agent_id"]), []).append((join["sequence"], leave["sequence"] if leave else float("inf")))
    for spans in intervals.values():
        spans.sort()
        require(all(left[1] < right[0] for left, right in zip(spans, spans[1:])), "overlapping membership intervals")
    memberships = sources["team_members"]
    for membership in memberships:
        interval = get("membership_intervals", membership["interval_id"])
        require(interval["team_id"] == membership["team_id"] and interval["agent_id"] == membership["agent_id"] and interval["leave_event_id"] is None, "current membership interval mismatch")
    declared = ({(row["team_id"], row["agent_id"]) for row in memberships}
                if current_memberships is None else set(current_memberships))
    opened = {(row["team_id"], row["agent_id"]) for row in rows["membership_intervals"] if row["leave_event_id"] is None}
    require(opened <= declared if partial_memberships else opened == declared, "open intervals and current memberships disagree")

    def authorized(stream, agent_id, position):
        if stream["team_id"] is not None:
            return any(start < position < end for start, end in intervals.get((stream["team_id"], agent_id), ()))
        relationship = get("direct_relationships", stream["relationship_id"])
        return agent_id in (relationship["agent_a_id"], relationship["agent_b_id"])

    for row in rows["chat_messages"]:
        event = events[row["publication_event_id"]]
        stream = get("chat_streams", row["stream_id"])
        require(event["stream_id"] == row["stream_id"] and event["event_kind"] == "send", "message publication mismatch")
        require(event["actor_agent_id"] == row["author_agent_id"], "message author mismatch")
        operation = get("chat_operations", row["author_agent_id"], row["operation_key"])
        require(operation["result"].get("status") == "DELIVERED" and operation["result"].get("message_id") == row["message_id"], "message has no exact publication receipt")
        if row["invocation_id"] is not None:
            invocation = get("activity_invocations", row["invocation_id"])
            require(invocation["agent_id"] == row["author_agent_id"], "message invocation owner mismatch")
        else:
            operation = get("chat_operations", row["author_agent_id"], row["operation_key"])
            require(operation["invocation_id"] is None and operation["command"] in {"send_team", "send_direct"}
                    and operation["result"].get("message_id") == row["message_id"], "Host publication has no command evidence")
        require(authorized(stream, row["author_agent_id"], event["sequence"]), "publication outside membership")
        require((row["message_id"],) in indexes["chat_message_projections"], "published message has no body projection")
    revisions = {}
    for row in rows["chat_revisions"]:
        message = get("chat_messages", row["message_id"])
        event = events[row["event_id"]]
        require(type(row["markdown"]) is str and type(row["title"]) is str, "revision text type")
        require(event["stream_id"] == message["stream_id"] and event["actor_agent_id"] == message["author_agent_id"], "revision author or stream mismatch")
        require(event["event_kind"] == ("send" if row["revision_number"] == 1 else "edit"), "revision event kind mismatch")
        require(row["revision_number"] != 1 or row["event_id"] == message["publication_event_id"], "first revision has a different publication event")
        require(authorized(get("chat_streams", message["stream_id"]), message["author_agent_id"], event["sequence"]), "revision outside membership")
        revisions.setdefault(row["message_id"], []).append(row)
    for history in revisions.values():
        history.sort(key=lambda row: row["revision_number"])
        require([row["revision_number"] for row in history] == list(range(1, len(history) + 1)), "revision sequence gap")
        require(all(events[left["event_id"]]["sequence"] < events[right["event_id"]]["sequence"]
                    and left["committed_at"] <= right["committed_at"] for left, right in zip(history, history[1:])), "revision chronology mismatch")
    for row in rows["chat_withdrawals"]:
        message = get("chat_messages", row["message_id"])
        revision = get("chat_revisions", row["revision_id"])
        event = events[row["event_id"]]
        require(revision["message_id"] == row["message_id"] and row["actor_agent_id"] == message["author_agent_id"], "withdrawal owner mismatch")
        require(event["event_kind"] == "withdraw" and event["stream_id"] == message["stream_id"] and event["actor_agent_id"] == row["actor_agent_id"], "withdrawal event mismatch")
        require(0 <= row["committed_at"] - revision["committed_at"] <= row["window_seconds"], "withdrawal window expired")
        require(authorized(get("chat_streams", message["stream_id"]), row["actor_agent_id"], event["sequence"]), "withdrawal outside membership")
        history = revisions[row["message_id"]]
        require(all(events[item["event_id"]]["sequence"] < event["sequence"] for item in history)
                and revision["revision_number"] == max(item["revision_number"] for item in history), "withdrawal not based on the last revision")
    withdrawals = {row["message_id"]: row["withdrawal_id"] for row in rows["chat_withdrawals"]}
    for row in rows["chat_message_projections"]:
        revision = get("chat_revisions", row["revision_id"])
        require(revision["message_id"] == row["message_id"], "latest revision message mismatch")
        require(revision["revision_number"] == max(item["revision_number"] for item in revisions[row["message_id"]]), "latest revision projection stale")
        require(row["withdrawal_id"] == withdrawals.get(row["message_id"]), "current withdrawal projection mismatch")
    for row in rows["chat_personal_views"]:
        message = get("chat_messages", row["message_id"])
        stream = get("chat_streams", message["stream_id"])
        revision = get("chat_revisions", row["revision_id"])
        require(revision["message_id"] == row["message_id"], "view revision mismatch")
        require((row["read_revision_number"] or 0) <= revision["revision_number"], "read watermark exceeds authorized revision")
        position = events[message["publication_event_id"]]["sequence"]
        require(authorized(stream, row["agent_id"], position), "unauthorized personal view")
        if stream["team_id"]:
            interval = get("membership_intervals", row["interval_id"])
            require(interval["agent_id"] == row["agent_id"] and interval["team_id"] == stream["team_id"], "view membership owner mismatch")
            join, leave = events[interval["join_event_id"]], events.get(interval["leave_event_id"])
            require(join["sequence"] < position and (leave is None or position < leave["sequence"]), "view outside exact membership interval")
            require(row["view_kind"] != "live" or leave is None, "live view has a closed membership interval")
            if row["view_kind"] == "frozen":
                require(leave is not None and row["departure_cutoff"] == leave["sequence"], "frozen departure cutoff mismatch")
                require(events[revision["event_id"]]["sequence"] < row["departure_cutoff"], "post-departure revision leak")
        else:
            require(row["interval_id"] is None, "direct view has team interval")
            require(row["view_kind"] == "live", "a direct view cannot impersonate a frozen team archive")
        if row["view_kind"] == "live":
            projection = get("chat_message_projections", row["message_id"])
            require((row["revision_id"], row["withdrawal_id"]) == (projection["revision_id"], projection["withdrawal_id"]), "live personal projection mismatch")
        else:
            permitted = [item for item in revisions[row["message_id"]] if events[item["event_id"]]["sequence"] < row["departure_cutoff"]]
            require(revision["revision_number"] == max(item["revision_number"] for item in permitted), "frozen revision is not the departure-time projection")
            withdrawal_id = withdrawals.get(row["message_id"])
            withdrawal = get("chat_withdrawals", withdrawal_id) if withdrawal_id else None
            expected = withdrawal_id if withdrawal and events[withdrawal["event_id"]]["sequence"] < row["departure_cutoff"] else None
            require(row["withdrawal_id"] == expected, "frozen withdrawal projection mismatch")
        if row["withdrawal_id"]:
            withdrawal = get("chat_withdrawals", row["withdrawal_id"])
            require(withdrawal["message_id"] == row["message_id"], "view withdrawal mismatch")
            if row["departure_cutoff"]:
                require(events[withdrawal["event_id"]]["sequence"] < row["departure_cutoff"], "post-departure withdrawal leak")

    for message in rows["chat_messages"]:
        stream = get("chat_streams", message["stream_id"])
        position = events[message["publication_event_id"]]["sequence"]
        actual = {(view["agent_id"], view["interval_id"]) for view in rows["chat_personal_views"] if view["message_id"] == message["message_id"]}
        if stream["team_id"]:
            expected = {(interval["agent_id"], interval["interval_id"]) for interval in rows["membership_intervals"]
                        if interval["team_id"] == stream["team_id"] and events[interval["join_event_id"]]["sequence"] < position
                        and (interval["leave_event_id"] is None or position < events[interval["leave_event_id"]]["sequence"])}
        else:
            relation = get("direct_relationships", stream["relationship_id"])
            expected = {(relation["agent_a_id"], None), (relation["agent_b_id"], None)}
        require(actual == expected, "publication personal views are incomplete")
        if message["reply_message_id"]:
            require(any(view["agent_id"] == message["author_agent_id"] and view["message_id"] == message["reply_message_id"]
                        for view in rows["chat_personal_views"]), "reply has no authorized author view")

    validate_executions(rows, source, get, require)
    for row in rows["sleep_conditions"]:
        if row["execution_id"]:
            require(get("executions", row["execution_id"])["agent_id"] == get("sleep_plans", row["sleep_id"])["agent_id"], "sleep condition execution owner mismatch")
    for row in rows["agent_notifications"]:
        if row["system_event_id"]:
            owner = source("system_memory_events", row["system_event_id"])["agent_id"]
            require(owner is None or owner == row["agent_id"], "system notice owner mismatch")
        if row["publication_id"]:
            require(row["classification"] == "recovery" and get("publication_manifests", row["publication_id"])["status"] == "published", "provisional recovery notice is not deliverable")
        if row["execution_id"]:
            require(get("executions", row["execution_id"])["agent_id"] == row["agent_id"], "execution notice owner mismatch")
        if row["mail_id"]:
            owner = source("agent_inbox", row["mail_id"])["agent_id"]
            require(owner == row["agent_id"], "mail notice owner mismatch")
        if row["chat_message_id"]:
            message = get("chat_messages", row["chat_message_id"])
            stream = get("chat_streams", message["stream_id"])
            require((stream["team_id"] is not None) == (row["source_kind"] == "team_message"), "notification stream kind mismatch")
            require(authorized(stream, row["agent_id"], events[message["publication_event_id"]]["sequence"]), "unauthorized chat notice")
    for row in rows["notification_claims"]:
        notice, request = get("agent_notifications", row["notification_id"]), get("model_requests", row["model_request_id"])
        require(notice["agent_id"] == request["agent_id"] and row["frame_id"] == request["frame_id"], "notification claim owner/frame mismatch")
        require(row["status"] != "presented" or (request["dispatch_state"] == "sent" and request["outcome"] == "completed"), "presentation lacks confirmed request evidence")
    for row in rows["chat_reminder_previews"]:
        notice, revision = get("agent_notifications", row["notification_id"]), get("chat_revisions", row["revision_id"])
        require(notice["agent_id"] == row["agent_id"] and notice["chat_message_id"] == revision["message_id"], "reminder preview source mismatch")
        require(type(row["preview"]) is dict and set(row["preview"]) == {"title", "body"}
                and all(type(value) is str for value in row["preview"].values()), "invalid captured reminder preview")
        require(type(row["visibility"]) is dict, "invalid reminder visibility")
        view = get("chat_personal_views", row["visibility"].get("view_id"))
        require(view["agent_id"] == row["agent_id"] and view["message_id"] == revision["message_id"]
                and view["interval_id"] == row["visibility"].get("interval_id"), "reminder visibility owner mismatch")
        if view["departure_cutoff"]:
            require(events[revision["event_id"]]["sequence"] < view["departure_cutoff"], "post-departure reminder leak")
    for row in rows["recovery_incidents"]:
        for name, field in (("activity_invocations", "invocation_id"), ("executions", "execution_id")):
            if row[field]:
                require(get(name, row[field])["agent_id"] == row["agent_id"], "recovery affected-owner mismatch")
    for row in rows["parent_acceptances"]:
        if row["decision_agent_id"]:
            require(row["decision_agent_id"] == row["parent_agent_id"], "parent decision owner mismatch")
        if row["case_id"]:
            principal = (source("governance_cases", row["case_id"])["principal_agent_id"], source("governance_cases", row["case_id"])["principal_team_id"])
            require(tuple(principal) == (row["parent_agent_id"], row["parent_team_id"]), "prospective parent case mismatch")
    for row in rows["team_topology_events"]:
        if row["acceptance_id"]:
            acceptance = get("parent_acceptances", row["acceptance_id"])
            require(acceptance["approved"] == 1 and acceptance["attaching_team_id"] == row["team_id"]
                    and (acceptance["parent_agent_id"], acceptance["parent_team_id"]) == (row["new_parent_agent_id"], row["new_parent_team_id"]), "attachment acceptance mismatch")
        require(row["team_id"] not in {row["old_parent_team_id"], row["new_parent_team_id"]}, "self-parent topology event")
    for row in rows["team_position_cooldowns"]:
        event = get("team_topology_events", row["event_id"])
        require(event["team_id"] == row["team_id"] and event["transition"] in {"attachment", "migration", "voluntary_detachment"}, "position cooldown is not an own-position transition")
    ordinary_agents = {row["agent_id"] for row in sources["agents"]}
    ordinary_teams = {row["team_id"] for row in sources["teams"]}
    for row in rows["audit_runs"]:
        require(row["temporary_team_id"] not in ordinary_teams, "audit team leaked into ordinary topology")
        require(type(row["template"]) is dict and type(row["electorate"]) is list
                and bool(row["electorate"]) and all(type(identity) is str and identity.strip() for identity in row["electorate"])
                and len(set(row["electorate"])) == len(row["electorate"]), "audit template or electorate invalid")
        participants = sorted((participant for participant in rows["audit_participants"] if participant["audit_id"] == row["audit_id"]), key=lambda participant: participant["position"])
        if participants:
            require([participant["scoped_agent_id"] for participant in participants] == row["electorate"]
                    and [participant["position"] for participant in participants] == list(range(len(participants))), "audit electorate mismatch")
        require(row["status"] == "prepared" or bool(participants), "audit has no captured participants")
    for row in rows["audit_participants"]:
        require(row["scoped_agent_id"] not in ordinary_agents and type(row["identity_snapshot"]) is dict, "audit identity leaked into ordinary registrations")
    for row in rows["audit_model_requests"]:
        participant = get("audit_participants", row["audit_id"], row["scoped_agent_id"])
        require(participant["model_alias"] == row["model_alias"], "audit model alias mismatch")
    for row in rows["audit_execution_evidence"]:
        require(row["runtime_generation"] == get("audit_runs", row["audit_id"])["runtime_generation"], "audit execution generation mismatch")
        require(row["status"] not in {"completed", "failed", "cancelled"} or row["outcome_unconfirmed"] == 0, "audit terminal outcome cannot be uncertain")
    for row in rows["publication_manifests"]:
        require((row["status"] == "prepared") == (row["resolved_at"] is None), "publication decision timestamp mismatch")
        require(type(row["staged_files"]) is list and all(type(entry) is dict for entry in row["staged_files"]), "publication staging evidence type")
        paths = set()
        for entry in row["staged_files"]:
            require(set(entry) == {"final", "backup", "staged", "existed", "digest"}
                    and all(type(entry[key]) is str and entry[key] for key in ("final", "backup", "digest"))
                    and (entry["staged"] is None or type(entry["staged"]) is str and bool(entry["staged"]))
                    and type(entry["existed"]) is bool and len(entry["digest"]) == 64
                    and all(char in "0123456789abcdef" for char in entry["digest"]), "publication staging entry invalid")
            require(entry["final"] not in paths and entry["final"] != entry["backup"], "publication directory identity conflict")
            paths.add(entry["final"])
        require(row["resolved_at"] is None or row["resolved_at"] >= row["prepared_at"], "publication resolved before preparation")
    for message in sources["agent_messages"]:
        for field, name in (("invocation_id", "activity_invocations"), ("source_execution_id", "executions")):
            if message[field]:
                require(get(name, message[field])["agent_id"] == message["agent_id"], "personal context source owner mismatch")
        if message["source_chat_message_id"]:
            require(any(view["agent_id"] == message["agent_id"] and view["message_id"] == message["source_chat_message_id"]
                        for view in rows["chat_personal_views"]), "personal context has no authorized chat view")
    segments = {row["segment_id"]: row for row in sources["agent_memory_segments"]}
    for segment in segments.values():
        if segment["invocation_id"]:
            require(get("activity_invocations", segment["invocation_id"])["agent_id"] == segment["agent_id"], "memory invocation owner mismatch")
    for card in sources["agent_memory_cards"]:
        require(card["invocation_id"] == segments[card["segment_id"]]["invocation_id"], "memory card invocation provenance mismatch")

