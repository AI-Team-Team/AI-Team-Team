"""Deliberate publications and author changes with atomic recipient evidence."""

from contextlib import asynccontextmanager

from ai_team_team.core.exceptions import ToolBusinessError
from ..activity.values import capture
from .base import identity
from .markdown import extract


class WriteMixin:
    def stream_for_team(self, team):
        return next(row for row in self.rows("chat_streams") if row.values["team_id"] == team.team_id)

    @asynccontextmanager
    async def message_lock(self, message_id):
        message = self.manager._records.index.get(("chat_messages", (message_id,)))
        if message is None:
            raise PermissionError("No authorized personal view of this message is available.")
        stream = self.manager._records.index[("chat_streams", (message.values["stream_id"],))]
        if stream.values["team_id"]:
            lock = self.manager.teams[stream.values["team_id"]].state_lock
        else:
            relation = self.manager._records.index[("direct_relationships", (stream.values["relationship_id"],))]
            lock = self.contact_lock(relation.values["agent_a_id"], relation.values["agent_b_id"])
        async with lock:
            yield

    def event(self, stream, kind, actor):
        event = capture(self.manager, "chat_events", event_id=identity("CE"),
            stream_id=stream.values["stream_id"], sequence=stream.values["next_position"],
            event_kind=kind, actor_agent_id=actor.agent_id if actor else None, created_at=self.clock.wall_time())
        cursor = capture(self.manager, "chat_streams", **{**dict(stream.values),
            "next_position": stream.values["next_position"] + 1})
        return event, cursor

    def arrivals(self, actor, views, revision, stream):
        records, notice_ids = [], []
        title, preview = extract(revision.values["markdown"], self.manager.config.conversations)
        for view in views:
            owner = view.values["agent_id"]
            if owner == actor.agent_id or view.values["deleted"] or view.values["view_kind"] != "live":
                continue
            self.manager._activity.require_agent(owner)
            notice_id = identity("NOTICE")
            previous = self.manager._records.index.get(("agent_activities", (owner,)))
            generation = previous.values["arrival_generation"] + 1 if previous else 1
            notice = capture(self.manager, "agent_notifications", notification_id=notice_id, agent_id=owner,
                source_kind="team_message" if stream.values["team_id"] else "direct_message",
                chat_message_id=view.values["message_id"], classification="ordinary",
                deduplication_key=f"chat:{revision.values['revision_id']}", arrival_generation=generation,
                created_at=self.clock.wall_time())
            from ..activity.values import Session
            session = self.manager._activity.sessions.get(owner) or Session(owner, identity("ADMISSION"), self.manager._resources.generation, active=False, intent="idle")
            records.extend((notice, self.manager._activity.marker(session, arrival_generation=generation),
                capture(self.manager, "chat_reminder_previews", notification_id=notice_id, agent_id=owner,
                    revision_id=revision.values["revision_id"], preview={"title": title, "body": preview},
                    visibility={"view_id": view.values["view_id"], "interval_id": view.values["interval_id"]})))
            notice_ids.append(notice_id)
        return records, tuple(notice_ids)

    def publication(self, actor, stream, markdown, key, recipients, *, reply_to=None):
        title, _ = extract(markdown, self.manager.config.conversations)
        if reply_to is not None:
            self.view(actor, reply_to)
        event, cursor = self.event(stream, "send", actor)
        message_id = identity("MSG")
        session = self.manager._activity.current.get()
        message = capture(self.manager, "chat_messages", message_id=message_id,
            stream_id=stream.values["stream_id"], author_agent_id=actor.agent_id,
            publication_event_id=event.values["event_id"], invocation_id=session.invocation_id if session else None,
            operation_key=key, reply_message_id=reply_to, created_at=self.clock.wall_time())
        revision = capture(self.manager, "chat_revisions", revision_id=identity("REV"), message_id=message_id,
            event_id=event.values["event_id"], revision_number=1, markdown=markdown, title=title,
            committed_at=self.clock.wall_time())
        views = []
        for owner in recipients:
            interval_id = None
            if stream.values["team_id"]:
                interval = next(row for row in self.rows("membership_intervals")
                    if row.values["team_id"] == stream.values["team_id"] and row.values["agent_id"] == owner
                    and row.values["leave_event_id"] is None)
                interval_id = interval.values["interval_id"]
            views.append(capture(self.manager, "chat_personal_views", view_id=identity("VIEW"), agent_id=owner,
                message_id=message_id, interval_id=interval_id, revision_id=revision.values["revision_id"],
                view_kind="live", unread_override=0, deleted=0))
        notices, notice_ids = self.arrivals(actor, views, revision, stream)
        records = [event, cursor, message, revision, *views, *notices,
            capture(self.manager, "chat_message_projections", message_id=message_id, revision_id=revision.values["revision_id"])]
        return records, {"status": "DELIVERED", "message_id": message_id, "notification_ids": notice_ids}, notice_ids

    async def send_team_message(self, team_id, markdown, *, actor=None, operation_key=None, reply_to=None):
        actor = self.actor(actor)
        extract(markdown, self.manager.config.conversations)
        operation = self.operation(actor, "send_team", [team_id, markdown, reply_to], operation_key)
        team = self.team(team_id, actor)
        async with team.state_lock, self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            previous = await self.replay(actor, "send_team", operation)
            if previous is not None:
                return previous
            self.team(team_id, actor)
            records, result, notices = self.publication(actor, self.stream_for_team(team), markdown,
                operation[0], [member.agent_id for member in team.members], reply_to=reply_to)
            return await self.finish(actor, "send_team", operation, records, result, notifications=notices)

    def require_author(self, actor, message_id):
        message = self.manager._records.index.get(("chat_messages", (message_id,)))
        if message is None or message.values["author_agent_id"] != actor.agent_id:
            raise PermissionError("Only the original author may change a shared message.")
        stream = self.manager._records.index[("chat_streams", (message.values["stream_id"],))]
        if stream.values["team_id"]:
            self.team(stream.values["team_id"], actor)
        return message, stream

    async def change_message(self, message_id, *, markdown=None, withdraw=False, actor=None, operation_key=None):
        actor = self.actor(actor)
        command = "withdraw" if withdraw else "edit"
        if not withdraw:
            title, _ = extract(markdown, self.manager.config.conversations)
        operation = self.operation(actor, command, [message_id, markdown], operation_key)
        async with self.message_lock(message_id), self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            replay = await self.replay(actor, command, operation)
            if replay is not None:
                return replay
            message, stream = self.require_author(actor, message_id)
            projection = self.manager._records.index[("chat_message_projections", (message_id,))]
            if projection.values["withdrawal_id"]:
                raise ToolBusinessError("A withdrawn message cannot be edited or withdrawn again.")
            old_revision = self.manager._records.index[("chat_revisions", (projection.values["revision_id"],))]
            event, cursor = self.event(stream, command, actor)
            records = [event, cursor]
            if not stream.values["team_id"] and not withdraw:
                relation = self.manager._records.index[("direct_relationships", (stream.values["relationship_id"],))]
                other = relation.values["agent_b_id"] if actor.agent_id == relation.values["agent_a_id"] else relation.values["agent_a_id"]
                self.manager._activity.require_agent(other)
                # Editing deliberately redelivers content; it cannot bypass
                # current restrictions or the stranger publication allowance.
                records.append(self.check_delivery(relation, actor, consume=True))
            views = [row for row in self.rows("chat_personal_views") if row.values["message_id"] == message_id
                     and row.values["view_kind"] == "live"]
            notices = ()
            if withdraw:
                window = self.manager.config.conversations.withdrawal_window_seconds
                elapsed = self.clock.wall_time() - old_revision.values["committed_at"]
                if not 0 <= elapsed <= window:
                    raise ToolBusinessError("The configured withdrawal window has elapsed.")
                withdrawal = capture(self.manager, "chat_withdrawals", withdrawal_id=identity("WITHDRAWAL"),
                    message_id=message_id, revision_id=old_revision.values["revision_id"], actor_agent_id=actor.agent_id,
                    event_id=event.values["event_id"], window_seconds=window, committed_at=self.clock.wall_time())
                records.extend((withdrawal, capture(self.manager, "chat_message_projections", message_id=message_id,
                    withdrawal_id=withdrawal.values["withdrawal_id"])))
                records.extend(capture(self.manager, "chat_personal_views", view_id=view.values["view_id"],
                    withdrawal_id=withdrawal.values["withdrawal_id"]) for view in views)
                version = old_revision.values["revision_number"]
            else:
                version = old_revision.values["revision_number"] + 1
                revision = capture(self.manager, "chat_revisions", revision_id=identity("REV"), message_id=message_id,
                    event_id=event.values["event_id"], revision_number=version, markdown=markdown, title=title,
                    committed_at=self.clock.wall_time())
                records.extend((revision, capture(self.manager, "chat_message_projections", message_id=message_id,
                    revision_id=revision.values["revision_id"])))
                next_views = [capture(self.manager, "chat_personal_views", view_id=view.values["view_id"],
                    revision_id=revision.values["revision_id"], unread_override=1) for view in views]
                arrivals, notices = self.arrivals(actor, next_views, revision, stream)
                records.extend((*next_views, *arrivals))
            return await self.finish(actor, command, operation, records,
                {"status": "WITHDRAWN" if withdraw else "EDITED", "message_id": message_id, "version": version}, notifications=notices)
