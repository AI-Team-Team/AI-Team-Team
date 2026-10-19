"""Version-bound character reads and independent personal visibility controls."""

import hashlib

from ai_team_team.core.chat import ChatReadResult
from ai_team_team.core.exceptions import ToolArgumentError
from ai_team_team.gated_reader import FileReadRangeError, FileSourceSlice, FileVersionChangedError
from ..activity.values import capture


class ReadMixin:
    def read_projection(self, actor, message_id, version=None):
        index = self.manager._records.index
        view = self.view(actor, message_id, index=index)
        current = index[("chat_revisions", (view.values["revision_id"],))]
        if version is not None and (type(version) is not int or version < 1):
            raise ToolArgumentError("A message version must be a positive integer.")
        if view.values["withdrawal_id"]:
            if version is not None:
                raise PermissionError("A withdrawn live source does not expose earlier revision bodies.")
            source = index[("chat_messages", (message_id,))]
            body = f"**{source.values['author_agent_id']} withdrew a message**"
        else:
            revision = current
            if version is not None:
                if version > current.values["revision_number"]:
                    raise PermissionError("That revision is outside the authorized personal view.")
                revision = next((row for row in index.values() if row.table_name == "chat_revisions"
                    and row.values["message_id"] == message_id and row.values["revision_number"] == version), None)
                if revision is None:
                    raise PermissionError("That revision is outside the authorized personal view.")
            body = revision.values["markdown"]
        token = hashlib.sha256(repr((message_id, current.values["revision_id"], view.values["withdrawal_id"],
            view.values["departure_cutoff"], version)).encode()).hexdigest()
        return view, current, body, token

    async def read_message(self, message_id, *, actor=None, version=None, start_line=1, end_line=None,
                           start_character=1, character_count=None, expected_file_version=None):
        async with self.read_delivery():
            return await self._read_message(message_id, actor=actor, version=version, start_line=start_line,
                end_line=end_line, start_character=start_character, character_count=character_count,
                expected_file_version=expected_file_version)

    async def _read_message(self, message_id, *, actor=None, version=None, start_line=1, end_line=None,
                           start_character=1, character_count=None, expected_file_version=None):
        with self.manager._resources.mutation():
            actor = self.actor(actor)
            view, current, body, token = self.read_projection(actor, message_id, version)

        def source_reader(_path, *, start_line, end_line, start_character, character_count, maximum_characters, expected_file_version):
            if expected_file_version is not None and expected_file_version != token:
                raise FileVersionChangedError()
            text = body.replace("\r\n", "\n").replace("\r", "\n")
            lines = text.split("\n")
            if start_line > len(lines) or start_character > len(lines[start_line - 1]) + 1:
                raise FileReadRangeError("The requested character range is beyond this message version.")
            start = sum(len(line) + 1 for line in lines[:start_line - 1]) + start_character - 1
            end = len(text)
            if end_line is not None:
                end = min(end, sum(len(line) + 1 for line in lines[:end_line]))
            if character_count is not None:
                end = min(end, start + character_count)
            stop = min(end, start + maximum_characters)
            selected = text[start:stop]
            complete = stop >= end
            next_line, next_character = start_line, start_character
            for character in selected:
                if character == "\n":
                    next_line, next_character = next_line + 1, 1
                else:
                    next_character += 1
            return FileSourceSlice(selected, complete, None if complete else next_line,
                                   None if complete else next_character, token)

        result = await self.manager._library_service._read_model_file(actor, None, message_id,
            start_line=start_line, end_line=end_line, start_character=start_character, character_count=character_count,
            expected_file_version=expected_file_version, source_reader=source_reader)
        async with self.message_lock(message_id), self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            live_view, _, _, current_token = self.read_projection(actor, message_id, version)
            if token != current_token:
                raise FileVersionChangedError()
            source = self.manager._records.index[("chat_messages", (message_id,))]
            reply = source.values["reply_message_id"]
            if reply:
                try:
                    self.view(actor, reply)
                except PermissionError:
                    reply = None
            delivered = ChatReadResult(**result.model_dump(), message_id=message_id,
                version=version or current.values["revision_number"], withdrawn=bool(view.values["withdrawal_id"]),
                frozen=view.values["view_kind"] == "frozen", reply_message_id=reply)
            if delivered.content:
                await self.acknowledge_read(actor, live_view, delivered.version)
            return delivered

    async def personal_control(self, command, message_id, *, actor=None, operation_key=None):
        actor = self.actor(actor)
        operation = self.operation(actor, command, [message_id], operation_key)
        async with self.message_lock(message_id), self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            replay = await self.replay(actor, command, operation)
            if replay is not None:
                return replay
            view = self.view(actor, message_id, include_deleted=command in {"restore_message", "delete_message"})
            revision = self.manager._records.index[("chat_revisions", (view.values["revision_id"],))]
            changes = {
                "mark_message_read": {"read_at": self.clock.wall_time(), "read_revision_number": revision.values["revision_number"], "unread_override": 0},
                "mark_message_unread": {"unread_override": 1},
                "delete_message": {"deleted": 1},
                "restore_message": {"deleted": 0},
            }.get(command)
            if changes is None:
                raise ToolArgumentError("Unknown personal message control.")
            record = capture(self.manager, "chat_personal_views", view_id=view.values["view_id"], **changes)
            return await self.finish(actor, command, operation, (record,),
                {"status": command.upper(), "message_id": message_id})

    async def set_chat_details(self, *, team_details=None, direct_details=None, actor=None, operation_key=None):
        actor = self.actor(actor)
        if any(value is not None and type(value) is not bool for value in (team_details, direct_details)):
            raise ToolArgumentError("Chat detail preferences require literal booleans.")
        operation = self.operation(actor, "chat_details", [team_details, direct_details], operation_key)
        async with actor.lifecycle_lock, self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            replay = await self.replay(actor, "chat_details", operation)
            if replay is not None:
                return replay
            current = self.manager._records.index.get(("chat_preferences", (actor.agent_id,)))
            defaults = self.manager.config.conversations
            record = capture(self.manager, "chat_preferences", agent_id=actor.agent_id,
                team_details=int(team_details if team_details is not None else bool(current.values["team_details"]) if current else defaults.team_details),
                direct_details=int(direct_details if direct_details is not None else bool(current.values["direct_details"]) if current else defaults.direct_details))
            return await self.finish(actor, "chat_details", operation, (record,), {"status": "PREFERENCES_UPDATED"})
