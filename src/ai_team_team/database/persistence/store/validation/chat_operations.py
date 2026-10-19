"""Command-specific receipt evidence, shared by SQL and detached validation."""

import json

from ai_team_team.core.activity.contracts.notifications import SourceDeliveryReceipt
from ai_team_team.core.chat import ChatOperationResult, _command_digest


PERSONAL_COMMANDS = frozenset({"mark_message_read", "mark_message_unread", "delete_message", "restore_message"})
RELATIONSHIP_STATUSES = {
    "block_agent": {"BLOCKED"},
    "unblock_agent": {"UNBLOCKED"},
    "remove_friendship": {"REMOVED"},
    "lift_direct_refusal": {"REFUSAL_LIFTED"},
    "request_friendship": {"PENDING", "ALREADY_FRIENDS"},
    "accept_friendship": {"ACCEPTED", "STALE_REQUEST", "ALREADY_RESOLVED"},
    "reject_friendship": {"REJECTED", "STALE_REQUEST", "ALREADY_RESOLVED"},
    "ignore_friendship": {"IGNORED", "STALE_REQUEST", "ALREADY_RESOLVED"},
    "cancel_friendship_request": {"CANCELLED", "STALE_REQUEST", "ALREADY_RESOLVED"},
}
PREFERENCE_DIGESTS = frozenset(_command_digest("chat_details", [team, direct])
    for team in (None, False, True) for direct in (None, False, True))


def validate_chat_operations(rows, get, require):
    revisions = {(row["message_id"], row["revision_number"]): row for row in rows["chat_revisions"]}
    withdrawals = {row["message_id"]: row for row in rows["chat_withdrawals"]}
    personal_views = {(row["agent_id"], row["message_id"]) for row in rows["chat_personal_views"]}
    accepted = {(row["relationship_id"], row["generation"]) for row in rows["friendship_requests"]
                if row["status"] == "accepted"}
    for operation in rows["chat_operations"]:
        result, command, owner = operation["result"], operation["command"], operation["agent_id"]
        require(type(result) is dict and type(result.get("status")) is str, "chat operation result is invalid")
        digest = operation["request_digest"]
        require(len(digest) == 64 and all(character in "0123456789abcdef" for character in digest), "chat operation digest is invalid")
        if operation["invocation_id"] is not None:
            require(get("activity_invocations", operation["invocation_id"])["agent_id"] == owner, "chat operation actor mismatch")
        try:
            model = SourceDeliveryReceipt if result["status"] == "DELIVERED" else ChatOperationResult
            model.model_validate_json(json.dumps({**result, "durability": "durable", "state_version": 1}))
        except (TypeError, ValueError):
            require(False, "invalid chat operation receipt")

        if command in {"send_team", "send_direct"}:
            require(set(result) == {"status", "message_id", "notification_ids"}
                    and result["status"] == "DELIVERED", "publication receipt command mismatch")
            message = get("chat_messages", result["message_id"])
            stream = get("chat_streams", message["stream_id"])
            require((command == "send_team") == (stream["team_id"] is not None), "publication receipt stream mismatch")
            require(message["author_agent_id"] == owner and message["operation_key"] == operation["operation_key"]
                    and message["invocation_id"] == operation["invocation_id"], "publication receipt actor mismatch")
            original = revisions.get((message["message_id"], 1))
            require(original is not None, "publication receipt has no original revision")
            target = stream["team_id"]
            if command == "send_direct":
                pair = get("direct_relationships", stream["relationship_id"])
                require(owner in {pair["agent_a_id"], pair["agent_b_id"]}, "publication receipt endpoint mismatch")
                target = pair["agent_b_id"] if owner == pair["agent_a_id"] else pair["agent_a_id"]
            require(digest == _command_digest(command, [target, original["markdown"], message["reply_message_id"]]),
                    "publication receipt input digest mismatch")
            identifiers = result["notification_ids"]
            require(len(identifiers) == len(set(identifiers)), "duplicate publication receipt notice")
            for identifier in identifiers:
                notice = get("agent_notifications", identifier)
                require(notice["chat_message_id"] == message["message_id"] and notice["agent_id"] != owner,
                        "publication receipt notice mismatch")
        elif command in {"edit", "withdraw"}:
            require(set(result) == {"status", "message_id", "version"}
                    and result["status"] == ("EDITED" if command == "edit" else "WITHDRAWN"), "message change receipt command mismatch")
            message = get("chat_messages", result["message_id"])
            require(message["author_agent_id"] == owner, "message change receipt author mismatch")
            revision = revisions.get((result["message_id"], result["version"]))
            require(revision is not None, "message change receipt revision is missing")
            if command == "edit":
                require(result["version"] > 1 and get("chat_events", revision["event_id"])["event_kind"] == "edit",
                        "edit receipt has no edit evidence")
            else:
                withdrawal = withdrawals.get(result["message_id"])
                require(withdrawal is not None and withdrawal["revision_id"] == revision["revision_id"]
                        and withdrawal["actor_agent_id"] == owner, "withdrawal receipt has no withdrawal evidence")
            require(digest == _command_digest(command, [message["message_id"], revision["markdown"] if command == "edit" else None]),
                    "message change receipt input digest mismatch")
        elif command in PERSONAL_COMMANDS:
            require(set(result) == {"status", "message_id"} and result["status"] == command.upper(),
                    "personal control receipt command mismatch")
            get("chat_messages", result["message_id"])
            require((owner, result["message_id"]) in personal_views, "personal control receipt has no authorized view")
            require(digest == _command_digest(command, [result["message_id"]]), "personal control receipt input digest mismatch")
        elif command == "chat_details":
            require(result == {"status": "PREFERENCES_UPDATED"}, "chat preference receipt command mismatch")
            get("chat_preferences", owner)
            require(digest in PREFERENCE_DIGESTS, "chat preference receipt input digest mismatch")
        else:
            require(command in RELATIONSHIP_STATUSES and result["status"] in RELATIONSHIP_STATUSES[command],
                    "relationship receipt command mismatch")
            validate_relationship_receipt(operation, accepted, get, require)


def validate_relationship_receipt(operation, accepted, get, require):
    """Validate historical consent without equating it with today's relationship."""
    result, command, owner = operation["result"], operation["command"], operation["agent_id"]
    fields = {"status", "relationship_id", "generation"}
    needs_request = command in {"accept_friendship", "reject_friendship", "ignore_friendship", "cancel_friendship_request"}
    needs_request = needs_request or (command == "request_friendship" and result["status"] == "PENDING")
    if needs_request:
        fields.add("request_id")
    require(set(result) == fields, "relationship receipt fields mismatch")
    relation = get("direct_relationships", result["relationship_id"])
    require(owner in {relation["agent_a_id"], relation["agent_b_id"]}, "relationship receipt endpoint mismatch")
    require(type(result["generation"]) is int and 0 < result["generation"] <= relation["generation"],
            "relationship receipt generation mismatch")
    responding = command in {"accept_friendship", "reject_friendship", "ignore_friendship", "cancel_friendship_request"}
    other = relation["agent_b_id"] if owner == relation["agent_a_id"] else relation["agent_a_id"]
    arguments = [None, result["request_id"]] if responding else [other, None]
    require(operation["request_digest"] == _command_digest(command, arguments), "relationship receipt input digest mismatch")
    if result["status"] == "ALREADY_FRIENDS":
        require((result["relationship_id"], result["generation"]) in accepted, "friendship receipt has no accepted consent")
    if not needs_request:
        return
    request = get("friendship_requests", result["request_id"])
    require(request["relationship_id"] == result["relationship_id"], "friendship receipt relationship mismatch")
    acting_field = "sender_agent_id" if command in {"request_friendship", "cancel_friendship_request"} else "recipient_agent_id"
    require(request[acting_field] == owner, "friendship receipt actor mismatch")
    if result["status"] == "STALE_REQUEST":
        require(request["generation"] < result["generation"], "stale friendship receipt is not stale")
    else:
        require(request["generation"] == result["generation"], "friendship receipt generation mismatch")
    if result["status"] == "ALREADY_RESOLVED":
        require(request["status"] != "pending", "resolved friendship receipt is still pending")
    elif result["status"] not in {"PENDING", "STALE_REQUEST"}:
        require(request["status"] == result["status"].lower(), "friendship receipt outcome mismatch")
