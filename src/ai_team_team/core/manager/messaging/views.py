"""One authorization projection for metadata, previews, bodies, and read controls."""

import hashlib
import json

from ai_team_team.core.activity.contracts import ChatMessagePage, ChatMessageSummary
from ai_team_team.core.exceptions import ToolArgumentError
from .markdown import extract
from .base import inspected


class ViewMixin:
    def view(self, actor, message_id, *, include_deleted=False, index=None):
        index = self.manager._records.index if index is None else index
        views = [row for row in index.values() if row.table_name == "chat_personal_views"
                 and row.values["agent_id"] == actor.agent_id and row.values["message_id"] == message_id
                 and (include_deleted or not row.values["deleted"])]
        if not views:
            raise PermissionError("No authorized personal view of this message is available.")
        return max(views, key=lambda row: (row.values["view_kind"] == "live", row.values["departure_cutoff"] or 0))

    def stream(self, *, team_id=None, other_agent_id=None, actor):
        if (team_id is None) == (other_agent_id is None):
            raise ToolArgumentError("Select exactly one team or direct conversation.")
        index = self.manager._records.index
        if team_id is not None:
            if not any(row.table_name == "membership_intervals" and row.values["team_id"] == team_id
                       and row.values["agent_id"] == actor.agent_id for row in index.values()):
                raise PermissionError("The actor has no authorized history in this conversation.")
            return next(row for row in index.values() if row.table_name == "chat_streams" and row.values["team_id"] == team_id)
        relation = self.find_pair(actor.agent_id, other_agent_id)
        if relation is None:
            return None
        return next((row for row in index.values() if row.table_name == "chat_streams"
                     and row.values["relationship_id"] == relation.values["relationship_id"]), None)

    def summary(self, view, index, *, include_preview=True):
        values = view.values
        message = index[("chat_messages", (values["message_id"],))]
        revision = index[("chat_revisions", (values["revision_id"],))]
        withdrawn = values["withdrawal_id"] is not None
        preview = ""
        if include_preview:
            _, preview = extract(revision.values["markdown"], self.manager.config.conversations, validate_title=False)
        title = revision.values["title"]
        if withdrawn:
            title, preview = "", f"**{message.values['author_agent_id']} withdrew a message**"
        return ChatMessageSummary(message_id=values["message_id"], author_agent_id=message.values["author_agent_id"],
            version=revision.values["revision_number"], title=title or None, preview=preview,
            unread=(values["read_revision_number"] or 0) < revision.values["revision_number"] or bool(values["unread_override"]), withdrawn=withdrawn,
            frozen=values["view_kind"] == "frozen")

    @inspected
    def list_messages(self, *, team_id=None, other_agent_id=None, actor=None, unread_only=False,
                      query=None, limit=50, cursor=None, include_deleted=False):
        actor = self.actor(actor)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ToolArgumentError("limit must be an integer between 1 and 1000.")
        if type(unread_only) is not bool or type(include_deleted) is not bool:
            raise ToolArgumentError("Message filters require literal booleans.")
        if query is not None and (type(query) is not str or not query.strip()):
            raise ToolArgumentError("Search text must be nonblank.")
        if cursor is not None and (type(cursor) is not str or not cursor.strip()):
            raise ToolArgumentError("A page cursor must be nonblank opaque text.")
        stream = self.stream(team_id=team_id, other_agent_id=other_agent_id, actor=actor)
        if stream is None:
            return ChatMessagePage(items=(), total_count=0, unread_count=0)
        index = self.manager._records.index
        source_ids = {row.values["message_id"] for row in index.values() if row.table_name == "chat_messages"
                      and row.values["stream_id"] == stream.values["stream_id"]}
        views = [row for row in index.values() if row.table_name == "chat_personal_views"
                 and row.values["agent_id"] == actor.agent_id and row.values["message_id"] in source_ids
                 and (include_deleted or not row.values["deleted"])]
        views.sort(key=lambda row: (index[("chat_events", (index[("chat_messages", (row.values["message_id"],))].values["publication_event_id"],))].values["sequence"], row.values["view_id"]))
        selected = []
        for view in views:
            item = self.summary(view, index, include_preview=False)
            body = index[("chat_revisions", (view.values["revision_id"],))].values["markdown"]
            if unread_only and not item.unread:
                continue
            if query and (item.withdrawn or query.casefold() not in body.casefold()):
                continue
            selected.append((view, item))
        fingerprint = hashlib.sha256(json.dumps([actor.agent_id, stream.values["stream_id"], unread_only,
            query, include_deleted, [(row.values["view_id"], row.version) for row in views]]).encode()).hexdigest()
        start = 0
        if cursor is not None:
            entry = self.cursors.get(cursor)
            if entry is None or entry[0] != fingerprint:
                raise ToolArgumentError("The authorized page changed or its opaque cursor expired; start a fresh listing.")
            start = entry[1]
        next_cursor = None
        if start + limit < len(selected):
            from .base import identity
            next_cursor = identity("PAGE")
            self.cursors[next_cursor] = fingerprint, start + limit
            if len(self.cursors) > 4096:
                self.cursors.pop(next(iter(self.cursors)))
        return ChatMessagePage(items=tuple(self.summary(view, index) for view, _ in selected[start:start + limit]), total_count=len(selected),
            unread_count=sum(item.unread for _, item in selected), next_cursor=next_cursor)

    def can_present(self, notice):
        if not notice.values["chat_message_id"]:
            return True
        try:
            actor = self.manager._activity.require_agent(notice.values["agent_id"])
            view = self.view(actor, notice.values["chat_message_id"])
            return view.values["view_kind"] == "live"
        except PermissionError:
            return False

    def frame_summaries(self, actor, *, include_references=False):
        """Pure committed-value reads never acquire the relationship mutation lock."""
        index = self.manager._records.index
        groups = {}
        views = {}
        notices_by_message = {}
        for notice in index.values():
            if notice.table_name == "agent_notifications" and notice.values["agent_id"] == actor.agent_id:
                notices_by_message.setdefault(notice.values["chat_message_id"], []).append(notice)
        preference = index.get(("chat_preferences", (actor.agent_id,)))
        for row in index.values():
            if row.table_name != "chat_personal_views" or row.values["agent_id"] != actor.agent_id:
                continue
            if row.values["view_kind"] != "live" or row.values["deleted"]:
                continue
            item = self.summary(row, index, include_preview=False)
            if not item.unread:
                continue
            message = index[("chat_messages", (item.message_id,))]
            stream = index[("chat_streams", (message.values["stream_id"],))]
            key = stream.values["team_id"] or stream.values["relationship_id"]
            notices = notices_by_message.get(item.message_id, ())
            if notices and all(self.manager._activity.suppressed(notice) for notice in notices):
                continue
            views[item.message_id] = row
            groups.setdefault((key, stream.values["team_id"] is not None), []).append(item)
        lines, references = [], []
        reminders = {}
        if any(item.withdrawn for items in groups.values() for item in items):
            for preview in self.reminder_items(actor, respect_suppression=True, live_only=True):
                reminders.setdefault(preview.message_id, []).append(preview)
        for (source, is_team), items in sorted(groups.items()):
            lines.append(f"{'AgentTeam' if is_team else 'Direct chat'} {source}: {len(items)} unread messages (previews do not mark read).")
            references.append({"source_kind": "chat_summary", "conversation_id": source,
                               "unread_count": len(items), "message_ids": [item.message_id for item in items[:self.manager.config.conversations.summary_preview_limit]]})
            setting = "team_details" if is_team else "direct_details"
            details = bool(preference.values[setting]) if preference else getattr(self.manager.config.conversations, setting)
            if details:
                shown, total = [], 0
                maximum = self.manager.config.conversations.summary_preview_limit
                for item in items:
                    captured = reminders.get(item.message_id, ()) if item.withdrawn else ()
                    total += len(captured) or 1
                    if len(shown) >= maximum:
                        continue
                    if captured:
                        shown.extend(f"- {preview.message_id}, Captured V{preview.version} reminder {preview.notification_id} (source withdrawn): {preview.title or '(untitled)'} — {preview.preview}"
                                     for preview in captured[:maximum - len(shown)])
                    else:
                        full = self.summary(views[item.message_id], index)
                        shown.append(f"- {full.message_id}, Current V{full.version}, {full.author_agent_id} — {full.title or '(untitled)'}: {full.preview}")
                lines.extend(shown)
                if len(shown) < total:
                    lines.append(f"Showing {len(shown)} of {total} eligible previews for {len(items)} unread messages; use list_chat_reminders for captured reminders.")
        text = "\n".join(lines)
        return (text, references) if include_references else text
