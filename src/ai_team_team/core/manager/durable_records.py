"""Trusted domain commits over immutable records, with dispatch after receipt."""

import asyncio
import uuid
import time
import threading

from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.records import dependency_closure, merge_records, record_digest
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.receipts import CommitReceipt, settle_commit


class DurableRecordService:
    """One copy-on-write record index; workers receive values, never this object."""

    def __init__(self, manager):
        self.manager = manager
        self._index_lock = threading.RLock()
        self.index = {}
        self.lock = asyncio.Lock()
        self.receipts = {}

    def restore(self, records):
        with self._index_lock:
            self.index = {record.identity: record for record in records}

    def snapshot(self):
        with self._index_lock:
            return tuple(self.index.values())

    def _merge(self, records):
        """Do not lose another worker's update between COW read and replace."""
        with self._index_lock:
            self.restore(merge_records(self.snapshot(), records))

    def capture_memberships(self, team_ids):
        """Capture relationship facts without editing any Agent-owned field.

        Local volatile mutations and durable checkpoints share this producer;
        current projection prerequisites are included even when unchanged.
        The later chat phase supplies the shared live publication ordering API.
        """
        with self._index_lock:
            return self._capture_memberships(team_ids)

    def _capture_memberships(self, team_ids):
        captured = []
        for team_id in sorted(team_ids):
            team = self.manager.teams[team_id]
            previous = next((row for row in self.index.values()
                             if row.table_name == "chat_streams" and row.values["team_id"] == team_id), None)
            stream_id = previous.values["stream_id"] if previous else f"CS-{team_id}"
            stream = thaw(previous.values) if previous else {"stream_id": stream_id, "team_id": team_id, "relationship_id": None, "next_position": 1, "state_version": 1}
            opened = {row.values["agent_id"]: row for row in self.index.values()
                      if row.table_name == "membership_intervals" and row.values["team_id"] == team_id and row.values["leave_event_id"] is None}
            members = {member.agent_id for member in team.members}
            for agent_id in sorted(set(opened) ^ members):
                joining = agent_id in members
                event_id = uuid.uuid4().hex
                captured.append(DomainRecord.capture("chat_events", {
                    "event_id": event_id, "stream_id": stream_id, "sequence": stream["next_position"],
                    "event_kind": "join" if joining else "leave", "actor_agent_id": agent_id,
                    "created_at": time.time(), "created_version": max(1, self.manager._state_version),
                }))
                stream["next_position"] += 1
                if joining:
                    values = {"interval_id": uuid.uuid4().hex, "team_id": team_id, "agent_id": agent_id,
                              "stream_id": stream_id, "join_event_id": event_id, "leave_event_id": None, "state_version": 1}
                else:
                    values = thaw(opened[agent_id].values)
                    values.update(leave_event_id=event_id, state_version=opened[agent_id].version + 1)
                captured.append(DomainRecord.capture("membership_intervals", values))
            if previous is None or stream["next_position"] != previous.values["next_position"]:
                if previous:
                    stream["state_version"] = previous.version + 1
                captured.append(DomainRecord.capture("chat_streams", stream))
        self.restore(merge_records(self.snapshot(), captured))
        # A projection may have been recorded in memory before any database
        # export. Its first partial checkpoint still needs the concrete stream,
        # interval, and join-event targets, not only newly changed facts.
        prerequisites = tuple(row for row in self.index.values()
            if (row.table_name == "chat_streams" and row.values["team_id"] in team_ids)
            or (row.table_name == "membership_intervals" and row.values["team_id"] in team_ids
                and row.values["leave_event_id"] is None))
        return dependency_closure(merge_records(prerequisites, captured), self.index)

    async def commit(self, records, *, operation_id=None, notifications=()):
        """Commit a domain delta without flushing unrelated queued changes.

        Notification dispatch contains IDs and transition metadata only. A
        caller cancellation cannot release the mutation lock or drop dispatch
        after a successful accepted operation.
        """
        manager = self.manager
        records = tuple(DomainRecord.capture(record.table_name, record.values) for record in records)
        if operation_id is None:
            operation_id = uuid.uuid4().hex
        if type(operation_id) is not str or not operation_id.strip():
            raise ValueError("A domain operation requires a nonblank identity.")
        notifications = tuple(notifications)
        notice_ids = {record.values["notification_id"] for record in records if record.table_name == "agent_notifications"}
        if any(identifier not in notice_ids for identifier in notifications):
            raise ValueError("Post-commit dispatch must reference a notification in the accepted operation.")
        async with manager._runtime_gate:
            if manager._closing or manager._restore_in_progress:
                raise RuntimeError("Runtime admission is closed.")
            async with self.lock:
                digest = await asyncio.to_thread(record_digest, records)
                if operation_id in self.receipts:
                    previous, _previous_records = self.receipts[operation_id]
                    if previous.record_digest != digest:
                        raise ValueError("An operation ID cannot be reused for different records.")
                    return previous
                if manager.db_path:
                    previous = await manager._persistence.receipt(manager.db_path, operation_id, wait_pending=False)
                    if previous is not None:
                        if previous.record_digest != digest:
                            raise ValueError("An operation ID cannot be reused for different records.")
                        self.receipts[operation_id] = previous, records
                        return previous
                if manager._closing:
                    raise RuntimeError("Runtime admission closed before acceptance.")
                captured = dependency_closure(records, self.index)
                merge_records(self.snapshot(), records)
                dirty = manager._new_dirty_state()
                dirty["configs"] = True
                agents, teams = set(), set()
                for record in captured:
                    table = ACTIVITY_TABLES[record.table_name]
                    for constraint in table.foreign_key_constraints:
                        target = constraint.referred_table.name
                        values = [record.values[element.parent.name] for element in constraint.elements]
                        if any(value is None for value in values):
                            continue
                        if target == "agents":
                            agents.update(values)
                        elif target == "teams":
                            teams.update(values)
                        elif target == "agent_memory_segments":
                            dirty["memory_segments"].update(values)
                        elif target == "system_memory_events":
                            dirty["memory_events"].update(values)
                        elif target == "agent_inbox":
                            for agent in manager._agents_by_id.values():
                                if any(mail["message_id"] in values for mail in agent.agent_inbox):
                                    dirty["agent_inboxes"].add(agent.agent_id)
                        elif target == "governance_cases":
                            dirty["governance_rounds"].update(values)
                dirty["record_dependency_agents"] = agents
                dirty["record_dependency_teams"] = teams
                if not manager.db_path:
                    from ai_team_team.database.persistence.store.detached_validation import validate_detached_records
                    state = {
                        "agents": [{"agent_id": agent.agent_id, "name": agent.name, "lifecycle_state": agent.lifecycle_state} for agent in manager._agents_by_id.values()],
                        "teams": [{"team_id": team.team_id, "team_kind": "ordinary", "lifecycle_state": "active", "creator_type": "agent" if hasattr(team.creator, "agent_id") else "team", "creator_id": getattr(team.creator, "agent_id", getattr(team.creator, "team_id", None)), "members": tuple(member.agent_id for member in team.members)} for team in manager.teams.values() if team.team_kind == "ordinary"],
                        "agent_inboxes": {agent.agent_id: list(agent.agent_inbox) for agent in manager._agents_by_id.values()},
                        **manager._memory.snapshot(),
                        "governance_rounds": manager._governance.snapshot(),
                        "records": merge_records(self.snapshot(), captured),
                    }
                    await asyncio.to_thread(validate_detached_records, state, partial=True)
                    if manager._closing:
                        raise RuntimeError("Runtime admission closed before acceptance.")
                with manager._snapshot_lock:
                    manager._state_version += 1
                    version = manager._state_version
                    receipt = CommitReceipt(operation_id, version,
                        "durable" if manager.db_path else "volatile",
                        tuple(record.receipt_key for record in captured), digest)
                    if manager.db_path:
                        snapshot = manager._capture_state_snapshot(dirty)
                        snapshot["records"] = merge_records(snapshot.get("records", ()), captured)
                        snapshot["_operations"] = (receipt,)
                        future = asyncio.wrap_future(manager._persistence.submit(manager.db_path, snapshot))
                    else:
                        future = asyncio.get_running_loop().create_future()
                        future.set_result((receipt,))
                try:
                    committed_receipts = await settle_commit(future)
                    if receipt not in committed_receipts:
                        raise RuntimeError("The writer did not acknowledge this exact operation.")
                finally:
                    if future.done() and not future.cancelled() and future.exception() is None and receipt in future.result():
                        self._merge(records)
                        self.receipts[operation_id] = receipt, records
                        for notification_id in notifications:
                            manager._emit_callback("on_system_event", "notification_committed", {"notification_id": notification_id, "operation_id": operation_id})
                return receipt
