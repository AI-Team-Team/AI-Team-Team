"""Durable addressed arrivals and request-specific presentation evidence."""

import asyncio
import contextvars

from ai_team_team.core.activity.contracts import SourceDeliveryReceipt

from .values import Session, capture, identifier


class NotificationMixin:
    async def deliver_system_event(self, event):
        """Trusted framework ingress; ordinary mail cannot choose this profile."""
        classifications = {
            "membership_changed": "membership",
            "permission_changed": "permission",
            "health_incident": "health",
            "recovery_interruption": "recovery",
        }
        classification = classifications.get(event.event_type)
        if classification is None or self.manager._memory.events.get(event.event_id) is not event:
            raise PermissionError("A protected notice requires a registered trusted system event.")
        owner = event.agent_id
        self.require_agent(owner)
        async with self.lock:
            self.check_open()
            notice_id = f"NOTICE-{event.event_id}"
            if ("agent_notifications", (notice_id,)) not in self.manager._records.index:
                marker = self.manager._records.index.get(("agent_activities", (owner,)))
                generation = marker.values["arrival_generation"] + 1 if marker else 1
                session = self.sessions.get(owner) or Session(
                    owner, identifier("ADMISSION"), self.generation, active=False, intent="idle"
                )
                notice = capture(
                    self.manager,
                    "agent_notifications",
                    notification_id=notice_id,
                    agent_id=owner,
                    source_kind="system_event",
                    system_event_id=event.event_id,
                    classification=classification,
                    deduplication_key=f"system:{event.event_id}",
                    arrival_generation=generation,
                    created_at=self.clock.wall_time(),
                )
                dirty = self.manager._new_dirty_state()
                dirty["memory_events"].add(event.event_id)
                try:
                    await self.manager._records.commit(
                        (notice, self.marker(session, arrival_generation=generation)),
                        dirty=dirty,
                        notifications=(notice_id,),
                    )
                finally:
                    if ("agent_notifications", (notice_id,)) in self.manager._records.index:
                        self.schedule_notice(notice_id)
            else:
                self.schedule_notice(notice_id)
            return notice_id

    def pending_notices(self, agent_id):
        records = self.manager._records.snapshot()
        presented = {
            row.values["notification_id"]
            for row in records
            if row.table_name == "notification_claims" and row.values["status"] == "presented"
        }
        return sorted(
            (
                row
                for row in records
                if row.table_name == "agent_notifications"
                and row.values["agent_id"] == agent_id
                and self.notice_pending(row, presented=presented)
            ),
            key=lambda row: (
                row.values["classification"] == "ordinary",
                row.values["arrival_generation"],
                row.values["notification_id"],
            ),
        )

    def notice_pending(self, notice, *, presented=None):
        if presented is None:
            presented = {
                row.values["notification_id"]
                for row in self.manager._records.snapshot()
                if row.table_name == "notification_claims" and row.values["status"] == "presented"
            }
        return notice.values["notification_id"] not in presented and not self.suppressed(notice)

    def notice_can_wake(self, notice):
        if not self.notice_pending(notice):
            return False
        session = self.sessions.get(notice.values["agent_id"])
        return session is None or session.intent != "sleep" or self.matches_sleep(session, notice)

    def suppressed(self, notice):
        if notice.values["classification"] != "ordinary":
            return False
        for preference in self.manager._records.snapshot():
            if (
                preference.table_name != "notification_suppression"
                or preference.values["agent_id"] != notice.values["agent_id"]
            ):
                continue
            values = preference.values
            if not values["permanent"] and values["remaining_seconds"] <= 0:
                continue
            if values["scope"] == "all":
                return True
            source = self.notice_source(notice)
            if values["scope"] == "agent" and source == ("agent", values["source_agent_id"]):
                return True
            if values["scope"] == "agent_team" and source == (
                "agent_team",
                values["source_team_id"],
            ):
                return True
        return False

    def notice_source(self, notice):
        if notice.values["chat_message_id"]:
            message = self.manager._records.index[
                ("chat_messages", (notice.values["chat_message_id"],))
            ]
            stream = self.manager._records.index[("chat_streams", (message.values["stream_id"],))]
            return (
                ("agent_team", stream.values["team_id"])
                if stream.values["team_id"]
                else ("agent", message.values["author_agent_id"])
            )
        if notice.values["execution_id"]:
            return "execution", notice.values["execution_id"]
        return "agent", None

    def mail_records(self, agent_ids):
        records, identifiers = [], []
        manager = self.manager
        known = {
            row.values["mail_id"]
            for row in manager._records.snapshot()
            if row.table_name == "agent_notifications"
        }
        for agent_id in sorted(agent_ids):
            agent = self.require_agent(agent_id)
            previous = manager._records.index.get(("agent_activities", (agent_id,)))
            generation = previous.values["arrival_generation"] if previous else 0
            for mail in manager._inbox.list(agent_id, unread_only=False):
                if mail.message_id in known:
                    continue
                generation += 1
                notice_id = f"NOTICE-{mail.message_id}"
                records.append(
                    capture(
                        manager,
                        "agent_notifications",
                        notification_id=notice_id,
                        agent_id=agent_id,
                        source_kind="personal_mail",
                        mail_id=mail.message_id,
                        classification="ordinary",
                        deduplication_key=f"mail:{mail.message_id}",
                        arrival_generation=generation,
                        created_at=self.clock.wall_time(),
                    )
                )
                identifiers.append(notice_id)
            if generation != (previous.values["arrival_generation"] if previous else 0):
                session = self.sessions.get(agent_id) or Session(
                    agent_id, identifier("ADMISSION"), self.generation, active=False, intent="idle"
                )
                records.append(self.marker(session, arrival_generation=generation))
        return records, tuple(identifiers)

    async def commit_inbox_delta(self, dirty):
        """Internal domain producers commit mail and notice in the same receipt."""
        async with self.lock:
            records, notice_ids = self.mail_records(dirty["agent_inboxes"])
            team_ids = {
                team_id
                for team_id in dirty["teams"]
                if team_id in self.manager.teams
                and self.manager.teams[team_id].team_kind == "ordinary"
            }
            if team_ids:
                records = [
                    *self.manager._records.capture_memberships(team_ids, publish=False),
                    *records,
                ]
                dirty["_relationships_supplied"] = True
            try:
                await self.manager._records.commit(records, dirty=dirty, notifications=notice_ids)
            finally:
                committed = [
                    notice_id
                    for notice_id in notice_ids
                    if ("agent_notifications", (notice_id,)) in self.manager._records.index
                ]
                for notice_id in committed:
                    self.schedule_notice(notice_id)

    def schedule_notice(self, notice_id):
        notice = self.manager._records.index[("agent_notifications", (notice_id,))]
        agent_id = notice.values["agent_id"]
        if self.closing or self.manager._restore_in_progress:
            return
        if not self.notice_can_wake(notice):
            return
        self.schedule_activation(agent_id, notification_only=True)

    def schedule_activation(self, agent_id, *, notification_only=False):
        if self.closing or self.manager._closing:
            return
        if agent_id in self.activating:
            # A recovery request must not be lost behind a conditional arrival.
            self.activating[agent_id] |= not notification_only
            return
        self.activating[agent_id] = not notification_only

        async def admit():
            try:
                async with self.lock:
                    # A scheduled notice can be presented by an existing
                    # invocation before this task obtains the admission lock.
                    # Recheck all current arrivals so a newer one is not lost.
                    if not self.activating[agent_id] and not any(
                        self.notice_can_wake(notice) for notice in self.pending_notices(agent_id)
                    ):
                        return
                    previous = self.sessions.get(agent_id)
                    scope = (
                        previous.scope
                        if previous is not None and previous.intent in {"continuing", "sleep"}
                        else None
                    )
                    await self._activate_locked(agent_id, scope=scope)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.manager._emit_callback(
                    "on_system_event",
                    "activity_admission_deferred",
                    {"agent_id": agent_id, "error_type": type(error).__name__},
                )
            finally:
                self.activating.pop(agent_id, None)

        task = asyncio.create_task(
            admit(), context=contextvars.Context(), name=f"att-admit-{agent_id}"
        )
        self.dispatch_tasks.add(task)
        task.add_done_callback(self.dispatch_tasks.discard)

    async def deliver_mail(self, agent_id, *, message_type, payload, schedule=True, _on_commit=None):
        from ai_team_team.core.formation import AgentInboxMessage
        from ai_team_team.database.persistence.records import freeze, thaw

        self.require_agent(agent_id)
        # Validate the entire wire value before touching the recipient's inbox.
        safe_payload = thaw(freeze(payload))
        AgentInboxMessage(
            message_id=identifier("MAIL"),
            agent_id=agent_id,
            message_type=message_type,
            payload=safe_payload,
            created_at=self.clock.wall_time(),
        )
        async with self.lock:
            self.check_open()
            # Lifecycle transitions can finish while this ingress waits. Keep
            # the accepted owner reference for rollback even if it is removed.
            agent = self.require_agent(agent_id)
            operation_id = identifier("MAIL-COMMIT")
            mail_id = None
            notice_ids = ()
            try:
                mail_id = self.manager._inbox.notify(agent_id, message_type, safe_payload)
                dirty = self.manager._new_dirty_state()
                dirty["agent_inboxes"].add(agent_id)
                records, notice_ids = self.mail_records({agent_id})
                receipt = await self.manager._records.commit(
                    records, dirty=dirty, notifications=notice_ids, operation_id=operation_id
                )
            except BaseException:
                if operation_id not in self.manager._records.receipts and mail_id is not None:
                    with agent.inbox_lock:
                        agent.agent_inbox[:] = [
                            item for item in agent.agent_inbox if item["message_id"] != mail_id
                        ]
                raise
            finally:
                accepted = self.manager._records.receipts.get(operation_id)
                if accepted is not None and _on_commit is not None:
                    # Internal local dispatch, not an observer callback. A lost
                    # response cannot strand an accepted scoped instruction.
                    committed = accepted[0]
                    _on_commit(SourceDeliveryReceipt(
                        message_id=mail_id,
                        notification_ids=notice_ids,
                        durability=committed.durability,
                        state_version=committed.state_version,
                    ))
                for notice_id in notice_ids:
                    if (
                        schedule
                        and ("agent_notifications", (notice_id,)) in self.manager._records.index
                    ):
                        self.schedule_notice(notice_id)
            return SourceDeliveryReceipt(
                message_id=mail_id,
                notification_ids=notice_ids,
                durability=receipt.durability,
                state_version=receipt.state_version,
            )

    async def prepare_frame(self, session):
        async with self.lock:
            self.bound_window(session)
            agent = self.require_agent(session.agent_id)
            if (
                agent.messages
                and agent.messages[-1].get("role") == "assistant"
                and not agent.messages[-1].get("tool_calls")
            ):
                self.append(
                    session,
                    {
                        "role": "user",
                        "content": "Continue your own admitted activity. Deliberately choose idle or finite sleep when appropriate.",
                    },
                )
            notices = self.pending_notices(session.agent_id)[
                : self.manager.config.activity.notification_frame_limit
            ]
            session.frame_id = identifier("FRAME")
            session.frame_notices = tuple(notices)
            session.context_version += 1
            references = [
                {
                    "notification_id": item.values["notification_id"],
                    "source_kind": item.values["source_kind"],
                    "source_id": item.values["mail_id"]
                    or item.values["chat_message_id"]
                    or item.values["execution_id"]
                    or item.values["system_event_id"],
                }
                for item in notices
            ]
            if references:
                lines = [
                    "New addressed information (presentation is not reading, voting, or consent):"
                ]
                for item in references:
                    lines.append(
                        f"- {item['source_kind']}: {item['source_id']} (notification {item['notification_id']})."
                    )
                    if item["source_kind"] == "personal_mail":
                        mail = next(
                            (
                                mail
                                for mail in self.manager._inbox.list(
                                    session.agent_id, unread_only=False
                                )
                                if mail.message_id == item["source_id"]
                            ),
                            None,
                        )
                        if mail is not None and mail.message_type == "governance_choice_request":
                            lines.append(
                                f"You received a governance voting email `{mail.message_id}`. You may use open_agent_mail to inspect it and independently decide whether to use submit_governance_choice. Reading is not voting."
                            )
                        elif mail is not None and mail.message_type == "personal_instruction":
                            lines.append(str(mail.payload.get("text", "")))
                        else:
                            lines.append(
                                "Use open_agent_mail to inspect this mail; opening is not a reply or a public choice."
                            )
                self.append(session, {"role": "user", "content": "\n".join(lines)})
            record = capture(
                self.manager,
                "notification_frames",
                frame_id=session.frame_id,
                invocation_id=session.invocation_id,
                agent_id=session.agent_id,
                context_version=session.context_version,
                arrival_cutoff=max(
                    (item.values["arrival_generation"] for item in notices), default=0
                ),
                summary_references=references,
            )
            await self.checkpoint(session, extra=(record,))

    def claim_records(self, session, request_id, status):
        return tuple(
            capture(
                self.manager,
                "notification_claims",
                notification_id=row.values["notification_id"],
                model_request_id=request_id,
                frame_id=session.frame_id,
                status=status,
                observed_at=self.clock.wall_time(),
            )
            for row in session.frame_notices
        )
