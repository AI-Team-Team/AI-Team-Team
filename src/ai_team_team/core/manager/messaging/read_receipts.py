"""A prepared body read is not a delivered personal observation."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ai_team_team.database.persistence.receipts import settle_commit
from ai_team_team.database.persistence.records import thaw
from ..activity.values import capture
from .base import identity


@dataclass(frozen=True)
class ReadAcknowledgement:
    view_id: str
    returned_version: int
    observed_view_version: int
    read_at: float


class ReadReceiptMixin:
    @asynccontextmanager
    async def read_delivery(self):
        """Restore cannot replace the owner of an unfinished local read receipt."""
        token = object()
        with self.manager._resources.mutation():
            self.read_deliveries.add(token)
        try:
            yield
        finally:
            with self.manager._resources._lock:
                self.read_deliveries.discard(token)

    def read_acknowledgement_records(self, acknowledgements):
        """Caller owns the activity lock through the observation checkpoint."""
        groups = {}
        for acknowledgement in acknowledgements:
            groups.setdefault(acknowledgement.view_id, []).append(acknowledgement)
        records = []
        for view_id, items in groups.items():
            view = self.manager._records.index[("chat_personal_views", (view_id,))]
            revision = self.manager._records.index[("chat_revisions", (view.values["revision_id"],))]
            returned = max(item.returned_version for item in items)
            clear_override = any(item.returned_version == revision.values["revision_number"]
                and item.observed_view_version == view.version for item in items)
            records.append(capture(self.manager, "chat_personal_views", view_id=view_id,
                read_at=max(view.values["read_at"] or 0, *(item.read_at for item in items)),
                read_revision_number=max(view.values["read_revision_number"] or 0, returned),
                unread_override=0 if clear_override else view.values["unread_override"]))
        return tuple(records)

    async def acknowledge_read(self, actor, view, returned_version):
        acknowledgement = ReadAcknowledgement(view.values["view_id"], returned_version,
            view.version, self.clock.wall_time())
        session = self.manager._activity.current.get()
        execution_id = self.manager._active_tool_invocation_id.get()
        if session is not None and self.manager._active_tool_agent.get() is actor and execution_id:
            # Only a successfully appended observation may transfer this value
            # to the next window checkpoint. Cancelled Native siblings do not.
            session.prepared_chat_reads[execution_id] = acknowledgement
            return

        operation_id = identity("CHAT-READ")
        try:
            await self.manager._records.commit(self.read_acknowledgement_records((acknowledgement,)),
                                               operation_id=operation_id)
        except asyncio.CancelledError:
            if operation_id in self.manager._records.receipts:
                # Host readers have no Working Context checkpoint. Keep both
                # mutation locks until the unreturned read has been compensated;
                # preserve pre-existing read/unread facts rather than forcing unread.
                previous = capture(self.manager, "chat_personal_views", view_id=view.values["view_id"],
                    **{key: view.values[key] for key in ("read_at", "read_revision_number", "unread_override")})
                with self.manager._resources.settlement():
                    prepared = self.manager._records.index[view.identity]
                    proof = {"operation_id": operation_id, "prepared": thaw(prepared.values), "previous": thaw(view.values)}
                    compensation = asyncio.create_task(self.manager._records.commit((previous,), allow_closing=True,
                        read_compensations=(proof,)))
                    await settle_commit(compensation)
            raise
