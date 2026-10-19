"""Captured recipient previews are distinct from live source retrieval."""

import hashlib
import json

from ai_team_team.core.chat import ChatReminderPage, ChatReminderSummary
from ai_team_team.core.exceptions import ToolArgumentError
from .base import identity, inspected


class ReminderMixin:
    def reminder_items(self, actor, *, message_id=None, respect_suppression=False, live_only=False):
        index = self.manager._records.index
        items = []
        for evidence in index.values():
            if evidence.table_name != "chat_reminder_previews" or evidence.values["agent_id"] != actor.agent_id:
                continue
            notice = index[("agent_notifications", (evidence.values["notification_id"],))]
            if message_id is not None and notice.values["chat_message_id"] != message_id:
                continue
            if respect_suppression and self.manager._activity.suppressed(notice):
                continue
            view = index[("chat_personal_views", (evidence.values["visibility"]["view_id"],))]
            if view.values["deleted"] or (live_only and view.values["view_kind"] != "live"):
                continue
            revision = index[("chat_revisions", (evidence.values["revision_id"],))]
            current = index[("chat_revisions", (view.values["revision_id"],))]
            unread = revision.values["revision_number"] > (view.values["read_revision_number"] or 0)
            if not unread and not (view.values["unread_override"] and revision.values["revision_number"] == current.values["revision_number"]):
                continue
            message = index[("chat_messages", (view.values["message_id"],))]
            items.append(ChatReminderSummary(notification_id=notice.values["notification_id"], message_id=message.values["message_id"],
                author_agent_id=message.values["author_agent_id"], version=revision.values["revision_number"],
                title=evidence.values["preview"]["title"] or None,
                preview=evidence.values["preview"]["body"][:self.manager.config.conversations.preview_characters],
                unread=True, withdrawn=bool(view.values["withdrawal_id"]), frozen=view.values["view_kind"] == "frozen"))
        return sorted(items, key=lambda item: (item.message_id, item.version, item.notification_id))

    @inspected
    def list_chat_reminders(self, *, actor=None, message_id=None, limit=50, cursor=None):
        actor = self.actor(actor)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ToolArgumentError("limit must be an integer between 1 and 1000.")
        if message_id is not None:
            self.view(actor, message_id)
        items = self.reminder_items(actor, message_id=message_id)
        fingerprint = hashlib.sha256(json.dumps([actor.agent_id, "reminders", message_id,
            [(item.notification_id, item.version) for item in items]]).encode()).hexdigest()
        start = 0
        if cursor is not None:
            if type(cursor) is not str or cursor not in self.cursors or self.cursors[cursor][0] != fingerprint:
                raise ToolArgumentError("The authorized reminder page changed; start a fresh listing.")
            start = self.cursors[cursor][1]
        next_cursor = None
        if start + limit < len(items):
            next_cursor = identity("PAGE")
            self.cursors[next_cursor] = fingerprint, start + limit
            if len(self.cursors) > 4096:
                self.cursors.pop(next(iter(self.cursors)))
        return ChatReminderPage(items=tuple(items[start:start + limit]), total_count=len(items), next_cursor=next_cursor)
