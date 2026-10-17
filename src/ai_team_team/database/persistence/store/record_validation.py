"""Cross-row authority validation, shared by writes and detached checkpoint reads."""

from sqlalchemy import CheckConstraint, select, text

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.records import valid_request_outcome


def validate_records(session, *, current_memberships=None, partial_memberships=False):
    rows = {name: [dict(row) for row in session.execute(select(table)).mappings()]
            for name, table in ACTIVITY_TABLES.items()}
    indexes = {name: {tuple(row[column.name] for column in table.primary_key): row for row in rows[name]}
               for name, table in ACTIVITY_TABLES.items()}

    def require(condition, reason):
        if not condition:
            raise StateRestoreError(f"Invalid durable checkpoint: {reason}.")

    def get(name, *key):
        row = indexes[name].get(tuple(key))
        require(row is not None, f"missing {name} reference")
        return row

    for name, table in ACTIVITY_TABLES.items():
        for check in table.constraints:
            if isinstance(check, CheckConstraint):
                invalid = session.execute(text(f'SELECT 1 FROM "{name}" WHERE NOT ({check.sqltext}) LIMIT 1')).first()
                require(invalid is None, f"{name} check violation")
        for column in table.columns:
            for check in column.constraints:
                if isinstance(check, CheckConstraint):
                    invalid = session.execute(text(f'SELECT 1 FROM "{name}" WHERE NOT ({check.sqltext}) LIMIT 1')).first()
                    require(invalid is None, f"{name}.{column.name} check violation")

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
        owner = session.execute(text("SELECT agent_id FROM agent_memory_segments WHERE segment_id=:id"), {"id": row["segment_id"]}).scalar_one()
        require(owner == row["beneficiary_agent_id"], "index request beneficiary mismatch")

    for row in rows["friendship_requests"]:
        relation = get("direct_relationships", row["relationship_id"])
        require({row["sender_agent_id"], row["recipient_agent_id"]} == {relation["agent_a_id"], relation["agent_b_id"]}, "friendship endpoint mismatch")
        require(row["generation"] <= relation["generation"], "friendship request future generation")
        require(row["status"] != "accepted" or row["generation"] == relation["generation"], "stale friendship acceptance")
    events = {row["event_id"]: row for row in rows["chat_events"]}
    for row in rows["chat_streams"]:
        positions = [event["sequence"] for event in rows["chat_events"] if event["stream_id"] == row["stream_id"]]
        require(not positions or row["next_position"] > max(positions), "stream ordering cursor mismatch")
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
    memberships = list(session.execute(text("SELECT team_id, agent_id, interval_id FROM team_members")).mappings())
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
        invocation = get("activity_invocations", row["invocation_id"])
        require(event["stream_id"] == row["stream_id"] and event["event_kind"] == "send", "message publication mismatch")
        require(event["actor_agent_id"] == row["author_agent_id"] == invocation["agent_id"], "message author mismatch")
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
        position = events[message["publication_event_id"]]["sequence"]
        require(authorized(stream, row["agent_id"], position), "unauthorized personal view")
        if stream["team_id"]:
            interval = get("membership_intervals", row["interval_id"])
            require(interval["agent_id"] == row["agent_id"] and interval["team_id"] == stream["team_id"], "view membership owner mismatch")
            join, leave = events[interval["join_event_id"]], events.get(interval["leave_event_id"])
            require(join["sequence"] < position and (leave is None or position < leave["sequence"]), "view outside exact membership interval")
            if row["view_kind"] == "frozen":
                require(leave is not None and row["departure_cutoff"] == leave["sequence"], "frozen departure cutoff mismatch")
                require(events[revision["event_id"]]["sequence"] < row["departure_cutoff"], "post-departure revision leak")
        else:
            require(row["interval_id"] is None, "direct view has team interval")
        if row["withdrawal_id"]:
            withdrawal = get("chat_withdrawals", row["withdrawal_id"])
            require(withdrawal["message_id"] == row["message_id"], "view withdrawal mismatch")
            if row["departure_cutoff"]:
                require(events[withdrawal["event_id"]]["sequence"] < row["departure_cutoff"], "post-departure withdrawal leak")

    for row in rows["executions"]:
        invocation = get("activity_invocations", row["invocation_id"])
        require((row["agent_id"], row["scope_kind"], row["scope_team_id"], row["runtime_generation"]) ==
                (invocation["agent_id"], invocation["scope_kind"], invocation["scope_team_id"], invocation["runtime_generation"]), "execution captured scope mismatch")
        require(type(row["effects"]) is list and bool(row["effects"])
                and all(type(effect) is str and effect in {"read_only", "artifact_write", "domain_mutation", "self_modification", "undeclared"} for effect in row["effects"])
                and len(set(row["effects"])) == len(row["effects"]), "execution effects snapshot invalid")
    for row in rows["execution_payloads"]:
        require(get("executions", row["execution_id"])["agent_id"] == row["agent_id"], "payload owner mismatch")
    for row in rows["execution_observations"]:
        if row["attempt_id"]:
            require(get("execution_attempts", row["attempt_id"])["execution_id"] == row["execution_id"], "observation attempt mismatch")
    for row in rows["execution_controls"]:
        require(get("executions", row["execution_id"])["agent_id"] == row["requester_agent_id"], "control requester mismatch")
        require((row["acknowledgement"] == "acknowledged") == (row["acknowledged_at"] is not None), "control acknowledgement evidence mismatch")
    for row in rows["sleep_conditions"]:
        if row["execution_id"]:
            require(get("executions", row["execution_id"])["agent_id"] == get("sleep_plans", row["sleep_id"])["agent_id"], "sleep condition execution owner mismatch")
    for row in rows["agent_notifications"]:
        if row["system_event_id"]:
            owner = session.execute(text("SELECT agent_id FROM system_memory_events WHERE event_id=:id"), {"id": row["system_event_id"]}).scalar_one()
            require(owner is None or owner == row["agent_id"], "system notice owner mismatch")
        if row["publication_id"]:
            require(row["classification"] == "recovery" and get("publication_manifests", row["publication_id"])["status"] == "published", "provisional recovery notice is not deliverable")
        if row["execution_id"]:
            require(get("executions", row["execution_id"])["agent_id"] == row["agent_id"], "execution notice owner mismatch")
        if row["mail_id"]:
            owner = session.execute(text("SELECT agent_id FROM agent_inbox WHERE message_id=:id"), {"id": row["mail_id"]}).scalar_one()
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
    for row in rows["recovery_incidents"]:
        for name, field in (("activity_invocations", "invocation_id"), ("executions", "execution_id")):
            if row[field]:
                require(get(name, row[field])["agent_id"] == row["agent_id"], "recovery affected-owner mismatch")
    for row in rows["parent_acceptances"]:
        if row["decision_agent_id"]:
            require(row["decision_agent_id"] == row["parent_agent_id"], "parent decision owner mismatch")
        if row["case_id"]:
            principal = session.execute(text("SELECT principal_agent_id, principal_team_id FROM governance_cases WHERE case_id=:id"), {"id": row["case_id"]}).one()
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
    ordinary_agents = set(session.execute(text("SELECT agent_id FROM agents")).scalars())
    ordinary_teams = set(session.execute(text("SELECT team_id FROM teams")).scalars())
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
    for message in session.execute(text("SELECT agent_id, invocation_id, source_execution_id, source_chat_message_id FROM agent_messages")).mappings():
        for field, name in (("invocation_id", "activity_invocations"), ("source_execution_id", "executions")):
            if message[field]:
                require(get(name, message[field])["agent_id"] == message["agent_id"], "personal context source owner mismatch")
        if message["source_chat_message_id"]:
            require(any(view["agent_id"] == message["agent_id"] and view["message_id"] == message["source_chat_message_id"]
                        for view in rows["chat_personal_views"]), "personal context has no authorized chat view")
    segments = {row["segment_id"]: row for row in session.execute(text("SELECT segment_id, agent_id, invocation_id FROM agent_memory_segments")).mappings()}
    for segment in segments.values():
        if segment["invocation_id"]:
            require(get("activity_invocations", segment["invocation_id"])["agent_id"] == segment["agent_id"], "memory invocation owner mismatch")
    for card in session.execute(text("SELECT agent_id, invocation_id, segment_id FROM agent_memory_cards")).mappings():
        require(card["invocation_id"] == segments[card["segment_id"]]["invocation_id"], "memory card invocation provenance mismatch")
