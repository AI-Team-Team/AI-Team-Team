"""Trusted domain commits over immutable records, with dispatch after receipt."""

import asyncio
import uuid
import time
import threading

from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.records import dependency_closure, merge_records, record_digest
from ai_team_team.database.persistence.records import DomainRecord, thaw, freeze
from ai_team_team.database.persistence.receipts import CommitReceipt, settle_commit
from ai_team_team.database.persistence.store.validation.detached import DetachedValidationCache
from ..exceptions import RuntimeAdmissionClosedError


class DurableRecordService:
    """One copy-on-write record index; workers receive values, never this object."""

    def __init__(self, manager):
        self.manager = manager
        self._index_lock = threading.RLock()
        self.index = {}
        self.lock = asyncio.Lock()
        self.receipts = {}
        self.publishing_proposals = set()
        self._validation = DetachedValidationCache()

    def restore(self, records):
        records = tuple(records)
        activity = getattr(self.manager, "_activity", None)
        if activity is not None:
            activity.bind_clock_records(records)
        with self._index_lock:
            self.index = {record.identity: record for record in records}
            self._validation.invalidate()

    def snapshot(self):
        with self._index_lock:
            return tuple(self.index.values())

    def discard_initial_team(self, team_id):
        """Undo only unaccepted creation facts, without replacing newer facts."""
        with self._index_lock:
            streams = {row.values["stream_id"] for row in self.index.values()
                if row.table_name == "chat_streams" and row.values["team_id"] == team_id}
            self.index = {key: row for key, row in self.index.items()
                if not (row.table_name in {"chat_streams", "chat_events", "membership_intervals"}
                    and row.values["stream_id"] in streams)
                and not (row.table_name == "team_topology_events" and row.values["team_id"] == team_id)}
            self._validation.invalidate()

    def _merge(self, records, *, read_compensations=()):
        """Do not lose another worker's update between COW read and replace."""
        with self._index_lock:
            self.index = {record.identity: record for record in merge_records(self.snapshot(), records, read_compensations=read_compensations)}

    def capture_memberships(self, team_ids, *, publish=True):
        """Capture relationship facts without editing any Agent-owned field.

        Local volatile mutations and durable checkpoints share this producer;
        current projection prerequisites are included even when unchanged.
        The later chat phase supplies the shared live publication ordering API.
        """
        with self._index_lock:
            return self._capture_memberships(team_ids, publish=publish)

    def _capture_memberships(self, team_ids, *, publish=True):
        captured = []
        for team_id in sorted(team_ids):
            team = self.manager.teams[team_id]
            if not any(row.table_name == "team_topology_events" and row.values["team_id"] == team_id for row in self.index.values()):
                if team._position_revision != 1:
                    raise ValueError("A noninitial team position is missing its authoritative history.")
                captured.append(DomainRecord.capture("team_topology_events", {
                    "event_id": f"POSITION-CREATE-{team_id}", "team_id": team_id,
                    "new_parent_agent_id": getattr(team, "_parent_agent_id", None),
                    "new_parent_team_id": team.parent_team.team_id if team.parent_team else None,
                    "creator_agent_id": getattr(team.creator, "agent_id", None),
                    "creator_team_id": getattr(team.creator, "team_id", None),
                    "transition": "creation", "position_revision": 1, "notice_recipients": [],
                    "created_at": self.manager._activity.clock.wall_time(),
                    "created_version": max(1, self.manager._state_version),
                }))
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
                    "created_at": self.manager._activity.clock.wall_time(), "created_version": max(1, self.manager._state_version),
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
        messaging = getattr(self.manager, "_messaging", None)
        if messaging is not None:
            captured.extend(messaging.freeze_departures(captured, self.index))
        merged = merge_records(self.snapshot(), captured)
        if publish and captured:
            self.restore(merged)
        candidate = {row.identity: row for row in merged}
        # A projection may have been recorded in memory before any database
        # export. Its first partial checkpoint still needs the concrete stream,
        # interval, and join-event targets, not only newly changed facts.
        prerequisites = tuple(row for row in candidate.values()
            if (row.table_name == "chat_streams" and row.values["team_id"] in team_ids)
            or (row.table_name == "team_topology_events" and row.values["team_id"] in team_ids)
            or (row.table_name == "team_position_cooldowns" and row.values["team_id"] in team_ids)
            or (row.table_name == "membership_intervals" and row.values["team_id"] in team_ids
                and row.values["leave_event_id"] is None))
        return dependency_closure(merge_records(prerequisites, captured), candidate)

    async def commit(self, records, *, operation_id=None, notifications=(), dirty=None, allow_closing=False, agent_contexts=None, team_memberships=None, team_lifecycles=None, agent_registrations=None, team_proposals=None, team_parents=None, agent_models=None, broker_state=None, team_inboxes=None, governance_state=None, migration_state=None, read_compensations=(), authority_check=None, record_factory=None, bind_acceptance_time=None):
        """Commit a domain delta without flushing unrelated queued changes.

        Notification dispatch contains IDs and transition metadata only. A
        caller cancellation cannot release the mutation lock or drop dispatch
        after a successful accepted operation.
        """
        manager = self.manager
        manager._resources.check_authority()
        formation_publication = manager._formations.prepare_publication(dirty)
        if agent_contexts and (dirty is None or not set(agent_contexts).issubset(dirty["agents"])):
            raise ValueError("Checkpoint context overrides require an authoritative Agent delta.")
        if team_memberships and (dirty is None or not set(team_memberships).issubset(dirty["teams"])):
            raise ValueError("Membership publication requires an authoritative team delta.")
        if team_lifecycles and (dirty is None or not set(team_lifecycles).issubset(dirty["teams"])):
            raise ValueError("Lifecycle publication requires an authoritative team delta.")
        if agent_models and (dirty is None or not set(agent_models).issubset(dirty["agents"])):
            raise ValueError("Model publication requires an authoritative Agent delta.")
        if team_parents and (dirty is None or not set(team_parents).issubset(dirty["teams"])):
            raise ValueError("Parent publication requires an authoritative team delta.")
        if team_inboxes and (dirty is None or not set(team_inboxes).issubset(dirty["inboxes"])):
            raise ValueError("Inbox publication requires an authoritative organizational inbox delta.")
        if team_proposals and (dirty is None or not set(team_proposals).issubset(dirty["proposals"])):
            raise ValueError("Proposal publication requires an authoritative proposal delta.")
        if governance_state is not None and (dirty is None or not set(dirty["governance_cases"]).issubset(governance_state)):
            raise ValueError("Governance publication requires the corresponding authoritative case deltas.")
        if migration_state is not None and (dirty is None or not set(dirty["migration_requests"]).issubset(migration_state)):
            raise ValueError("Migration publication requires the corresponding authoritative request deltas.")
        registrations = agent_registrations or {}
        if registrations and (dirty is None or not set(registrations).issubset(dirty["agents"])
                or not {item.library_id for item in registrations.values()}.issubset(dirty["libraries"])):
            raise ValueError("Identity publication requires authoritative Agent and private library deltas.")
        records = tuple(DomainRecord.capture(record.table_name, record.values) for record in records)
        if record_factory is not None and (records or notifications or read_compensations):
            raise ValueError("An admission-time record factory cannot replace supplied records or delivery references.")
        if bind_acceptance_time is not None and record_factory is None:
            raise ValueError("Acceptance-time binding requires a prepared record factory.")
        # Freeze before the first await: an admission waiting for the runtime
        # gate already carries timestamps captured from this clock binding.
        manager._activity.bind_clock_records(records, pending_factory=record_factory is not None)
        read_compensations = tuple(freeze(proof) for proof in read_compensations)
        if operation_id is None:
            operation_id = uuid.uuid4().hex
        if type(operation_id) is not str or not operation_id.strip():
            raise ValueError("A domain operation requires a nonblank identity.")
        notifications = tuple(notifications)
        notice_ids = {record.values["notification_id"] for record in records if record.table_name == "agent_notifications"}
        if any(identifier not in notice_ids for identifier in notifications):
            raise ValueError("Post-commit dispatch must reference a notification in the accepted operation.")
        async with manager._runtime_gate:
            manager._resources.check_authority()
            for owner, item in registrations.items():
                if (manager._agent_registry.pending.get(owner) is not item or item.library is None
                        or item.generation != manager._resources.generation):
                    raise ValueError("The Agent registration reservation is no longer valid.")
            restoring_elsewhere = (
                manager._restore_in_progress
                and asyncio.current_task() is not manager._restore_finalizer
            )
            if manager._closed or (manager._closing and not allow_closing) or restoring_elsewhere:
                raise RuntimeAdmissionClosedError("Runtime admission is closed.")
            async with self.lock:
                manager._resources.check_authority()
                factory_receipt = None
                if record_factory is not None:
                    if manager.db_path:
                        factory_receipt = await manager._persistence.receipt(manager.db_path, operation_id, wait_pending=False)
                    manager._resources.check_authority()
                    if manager._closing and not allow_closing:
                        raise RuntimeAdmissionClosedError("Runtime admission closed before record production.")
                    # Only short trusted producers run here. They capture a
                    # transition's time after both admission queues, rather
                    # than spending a cooldown while waiting to enter them.
                    records = tuple(DomainRecord.capture(row.table_name, row.values) for row in record_factory())
                    manager._activity.bind_clock_records(records)
                for proof in read_compensations:
                    prepared = DomainRecord.capture("chat_personal_views", proof["prepared"])
                    prior = self.receipts.get(proof["operation_id"])
                    if prior is None or prior[1] != (prepared,) or self.index.get(prepared.identity) != prepared:
                        raise ValueError("Read compensation requires this exact unsettled-delivery receipt and projection.")
                    from ai_team_team.database.persistence.read_compensation import permits_read_compensation
                    if len(records) != 1 or not permits_read_compensation(prepared, records[0], (proof,)):
                        raise ValueError("Read compensation may restore only its immediately preceding personal read fields.")
                digest = await asyncio.to_thread(record_digest, records)
                time_template = None
                if bind_acceptance_time is not None:
                    from ai_team_team.database.persistence.acceptance_time import PreparedAcceptanceTime
                    time_template = await asyncio.to_thread(PreparedAcceptanceTime.prepare, records)
                if operation_id in self.receipts:
                    previous, _previous_records = self.receipts[operation_id]
                    if previous.record_digest != digest:
                        raise ValueError("An operation ID cannot be reused for different records.")
                    return previous
                if manager.db_path:
                    previous = factory_receipt if record_factory is not None else await manager._persistence.receipt(
                        manager.db_path, operation_id, wait_pending=False)
                    if previous is not None:
                        if previous.record_digest != digest:
                            raise ValueError("An operation ID cannot be reused for different records.")
                        self.receipts[operation_id] = previous, records
                        return previous
                if manager._closing and not allow_closing:
                    raise RuntimeAdmissionClosedError("Runtime admission closed before acceptance.")
                captured = dependency_closure(records, self.index)
                merge_records(self.snapshot(), records, read_compensations=read_compensations)
                checkpoint_dirty = dirty
                dirty = manager._new_dirty_state()
                if checkpoint_dirty is not None:
                    manager._merge_dirty_state(dirty, checkpoint_dirty)
                    dirty["_relationships_supplied"] = checkpoint_dirty.get("_relationships_supplied", False)
                    dirty["_creation_teams"] = checkpoint_dirty.get("_creation_teams", ())
                dirty["configs"] = True
                agents, teams, source_libraries = set(), set(), set()
                for record in captured:
                    if record.table_name == "executions":
                        source_libraries.update(reference["lib_id"] for reference in record.values["source_references"] or ()
                                                if reference["kind"] == "library")
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
                            dirty["governance_cases"].update(values)
                dirty["record_dependency_agents"] = agents
                dirty["record_dependency_teams"] = teams
                dirty["record_dependency_libraries"] = source_libraries
                if team_memberships:
                    dirty["team_memberships"] = team_memberships
                if team_lifecycles:
                    dirty["team_lifecycles"] = team_lifecycles
                if team_proposals:
                    dirty["team_proposals"] = team_proposals
                if team_parents:
                    dirty["team_parents"] = team_parents
                if team_inboxes:
                    dirty["team_inboxes"] = team_inboxes
                if agent_models:
                    dirty["agent_models"] = {owner: alias for owner, (alias, _client) in agent_models.items()}
                if registrations:
                    dirty["_staged_agents"] = {owner: item.agent for owner, item in registrations.items()}
                    dirty["_staged_libraries"] = {item.library_id: item.library for item in registrations.values()}
                validation_candidate = None
                if not manager.db_path:
                    scoped_auditors = {member.agent_id for team in manager.teams.values()
                                       if team.team_kind == "supervisory" for member in team.members}
                    hidden_teams = {team.team_id for team in manager.teams.values()
                        if getattr(team, "_publication_pending", False) and team.team_id not in dirty.get("_creation_teams", ())}
                    scoped_auditors.update(owner for team_id in hidden_teams
                        for owner in manager.teams[team_id]._provisional_agent_ids)
                    state = {
                        "agents": [{"agent_id": agent.agent_id, "name": agent.name, "lifecycle_state": agent.lifecycle_state} for agent in {**manager._agents_by_id, **dirty.get("_staged_agents", {})}.values() if agent.agent_id not in scoped_auditors],
                        "libraries": [{"lib_id": lib.lib_id, "name": lib.name, "library_kind": lib.library_kind,
                            "owner_agent_id": lib.owner_agent_id, "owner_team_id": lib.owner_team_id,
                            "lifecycle_state": lib.lifecycle_state, "description": lib.description,
                            "is_public_visible": lib.is_public_visible} for lib in manager.libraries.values()
                            if lib.owner_agent_id not in scoped_auditors and lib.owner_team_id not in hidden_teams],
                        "teams": [{"team_id": team.team_id, "position_revision": team._position_revision + (1 if team.team_id in (team_parents or {}) else 0), "team_kind": "ordinary", "lifecycle_state": (team_lifecycles or {}).get(team.team_id, getattr(team, "_lifecycle_state", "active")), "parent_team_id": (team_parents or {}).get(team.team_id, {}).get("parent_team_id", team.parent_team.team_id if team.parent_team else None), "parent_agent_id": (team_parents or {}).get(team.team_id, {}).get("parent_agent_id", getattr(team, "_parent_agent_id", None)), "creator_type": "agent" if hasattr(team.creator, "agent_id") else "team", "creator_id": getattr(team.creator, "agent_id", getattr(team.creator, "team_id", None)), "members": (team_memberships or {}).get(team.team_id, tuple(member.agent_id for member in team.members))} for team in manager.teams.values() if team.team_kind == "ordinary" and team.team_id not in hidden_teams],
                        "agent_inboxes": {agent.agent_id: [mail for mail in agent.agent_inbox
                            if manager._inbox.is_capturable(mail["message_id"])] for agent in manager._agents_by_id.values()
                            if agent.agent_id not in scoped_auditors},
                        **manager._memory.snapshot(),
                        "governance_cases": manager._governance.snapshot(),
                        "migration_requests": [item.model_dump(mode="json") for item in manager._migration.requests.values()],
                        "records": merge_records(self.snapshot(), captured, read_compensations=read_compensations),
                    }
                    validation_candidate = await asyncio.to_thread(self._validation.prepare, state)
                    if manager._closing and not allow_closing:
                        raise RuntimeAdmissionClosedError("Runtime admission closed before acceptance.")
                # Resource authorization precedes the snapshot lock, matching
                # managed file commits that publish their snapshot delta.
                manager._resources.check_authority()
                with manager._resources._lock, manager._snapshot_lock:
                    if formation_publication is not None:
                        formation_publication.validate()
                    if authority_check is not None:
                        authority_check()
                    if time_template is not None and not manager.db_path:
                        timestamp = manager._activity.clock.wall_time()
                        records, digest = time_template.bind(timestamp)
                        replacements = {row.identity: row for row in records}
                        captured = tuple(replacements.get(row.identity, row) for row in captured)
                        bind_acceptance_time(timestamp, manager._activity.clock.monotonic())
                        # The preflight graph proved the static relationships.
                        # Its earlier timestamp values are not an accepted cache.
                        validation_candidate = None
                        self._validation.invalidate()
                    manager._state_version += 1
                    version = manager._state_version
                    receipt = CommitReceipt(operation_id, version,
                        "durable" if manager.db_path else "volatile",
                        tuple(record.receipt_key for record in captured), digest)
                    if manager.db_path:
                        if formation_publication is not None:
                            dirty["_formation_state"] = formation_publication.projection()
                        snapshot = manager._capture_state_snapshot(dirty)
                        if agent_contexts:
                            # Capture the candidate only in its accepted value
                            # snapshot, never on a live person before receipt.
                            snapshot["agents"] = [
                                {**row, "last_context": agent_contexts[row["agent_id"]]}
                                if row["agent_id"] in agent_contexts else row
                                for row in snapshot["agents"]
                            ]
                        snapshot["records"] = merge_records(snapshot.get("records", ()), captured, read_compensations=read_compensations)
                        snapshot["_read_compensations"] = read_compensations
                        snapshot["_operations"] = (receipt,)
                        if time_template is not None:
                            from ai_team_team.database.persistence.acceptance_time import AcceptanceTimeBinding
                            if len(dirty["migration_requests"]) != 1:
                                raise ValueError("A timed position commit requires one migration request.")
                            snapshot["_acceptance_times"] = (AcceptanceTimeBinding(operation_id,
                                next(iter(dirty["migration_requests"])), time_template),)
                            future = asyncio.wrap_future(manager._persistence.submit(manager.db_path, snapshot,
                                acceptance_clock=manager._activity.clock))
                        else:
                            future = asyncio.wrap_future(manager._persistence.submit(manager.db_path, snapshot))
                        self.publishing_proposals.update(team_proposals or ())
                    else:
                        future = asyncio.get_running_loop().create_future()
                        future.set_result((receipt,))
                try:
                    return await self._settle_publication(future, receipt, records, operation_id, notifications,
                        validation_candidate, team_memberships, team_lifecycles, registrations, team_proposals, team_parents, agent_models, broker_state, team_inboxes, governance_state, migration_state, read_compensations, formation_publication,
                        time_template if manager.db_path else None, bind_acceptance_time)
                finally:
                    with manager._snapshot_lock:
                        self.publishing_proposals.difference_update(team_proposals or ())

    async def _settle_publication(self, future, receipt, records, operation_id, notifications,
            validation_candidate, team_memberships, team_lifecycles, registrations, team_proposals, team_parents, agent_models, broker_state, team_inboxes, governance_state, migration_state, read_compensations, formation_publication, time_template, bind_acceptance_time):
        manager = self.manager
        accepted = None

        def acknowledged(result):
            if time_template is None:
                if receipt not in result:
                    raise RuntimeError("The writer did not acknowledge this exact operation.")
                return receipt, records, None
            from dataclasses import replace
            from ai_team_team.database.persistence.acceptance_time import AcceptedTimedWrite
            if not isinstance(result, AcceptedTimedWrite):
                raise RuntimeError("The writer did not return this transition's acceptance time.")
            reading = dict(result.timestamps).get(operation_id)
            if reading is None:
                raise RuntimeError("The transition's acceptance time is missing from its acknowledgement.")
            committed_records, digest = time_template.bind(reading.wall_time)
            actual = replace(receipt, record_digest=digest)
            if actual not in result:
                raise RuntimeError("The timed writer acknowledgement has different authoritative values.")
            return actual, committed_records, reading

        try:
            committed_receipts = await settle_commit(future)
            accepted = acknowledged(committed_receipts)
        finally:
            if future.done() and not future.cancelled() and future.exception() is None:
                receipt, records, reading = accepted or acknowledged(future.result())
                if reading is not None:
                    bind_acceptance_time(reading.wall_time, reading.monotonic)
                def publish():
                    # Never retain resource authority while waiting for an
                    # unrelated topology reader. An accepted commit survives cancellation.
                    while True:
                        manager._resources._lock.acquire()
                        if manager._topology_lock.acquire(blocking=False):
                            break
                        manager._resources._lock.release()
                        if manager._topology_lock.acquire(timeout=0.05):
                            manager._topology_lock.release()
                    try:
                        with manager._snapshot_lock:
                            if formation_publication is not None:
                                formation_publication.publish()
                            if migration_state is not None:
                                manager._migration.publish(migration_state)
                            if governance_state is not None:
                                manager._governance.publish(governance_state)
                            if broker_state is not None:
                                manager.broker.publish_state(broker_state)
                            for team_id, inbox in (team_inboxes or {}).items():
                                with manager.teams[team_id].inbox_lock:
                                    manager.teams[team_id].message_inbox = list(inbox)
                            for item in registrations.values():
                                item.publish()
                            self._merge(records, read_compensations=read_compensations)
                            for owner, (alias, client) in (agent_models or {}).items():
                                manager._agents_by_id[owner].llm_client = client
                                manager._agents_by_id[owner]._model_alias = alias
                            for team_id, relation in (team_parents or {}).items():
                                parent = manager.teams.get(relation["parent_team_id"]) if relation["parent_team_id"] else manager._agents_by_id.get(relation["parent_agent_id"])
                                manager._topology.publish_parent(manager.teams[team_id], parent)
                            for team_id, proposals in (team_proposals or {}).items():
                                manager.teams[team_id].proposals = proposals
                            for team_id, member_ids in (team_memberships or {}).items():
                                manager.teams[team_id].members = [manager._agents_by_id[owner] for owner in member_ids]
                            for team_id, lifecycle in (team_lifecycles or {}).items():
                                manager.teams[team_id]._lifecycle_state = lifecycle
                    finally:
                        manager._topology_lock.release()
                        manager._resources._lock.release()

                publication = None
                if team_memberships or team_lifecycles or registrations or team_proposals or team_parents or agent_models or broker_state is not None or team_inboxes or governance_state is not None or migration_state is not None or formation_publication is not None:
                    publication = asyncio.create_task(asyncio.to_thread(publish))
                else:
                    self._merge(records, read_compensations=read_compensations)
                try:
                    if publication is not None:
                        await settle_commit(publication)
                finally:
                    if publication is None or (publication.done() and not publication.cancelled() and publication.exception() is None):
                        if validation_candidate is not None:
                            self._validation.accept(validation_candidate)
                        self.receipts[operation_id] = receipt, records
                        manager._topology.schedule_notices(records)
                        if team_parents or team_lifecycles:
                            manager.broker.schedule_route_review()
                        if team_memberships:
                            manager._governance.memberships_changed(set(team_memberships))
                        for notification_id in notifications:
                            manager._emit_callback("on_system_event", "notification_committed", {"notification_id": notification_id, "operation_id": operation_id})
        return receipt
