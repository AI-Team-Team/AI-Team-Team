"""Summary coverage changes reminders, never source read state or consent."""

from collections import Counter

from ..values import Session, capture, identifier


class SuppressionSummaryMixin:
    def covered_notice_ids(self):
        return self.coverage_index()[0]

    def coverage_index(self):
        index = self.manager._records.index
        previous = getattr(self, "_summary_coverage", None)
        if previous is None or previous[0] is not index:
            covered, summaries = set(), {}
            for row in index.values():
                if row.table_name == "notification_summary_items":
                    covered.add(row.values["notification_id"])
                    summaries.setdefault(row.values["summary_id"], []).append(row.values["notification_id"])
            previous = self._summary_coverage = index, frozenset(covered), summaries
        return previous[1], previous[2]

    def summary_event(self, notice):
        event = self.manager._memory.events.get(notice.values["system_event_id"])
        return event if event is not None and event.event_type == "notification_summary" else None

    def summary_source(self, notice):
        kind, source = self.notice_source(notice)
        if notice.values["mail_id"] and source is None:
            return "personal_mail", None
        return kind, source

    def eligible_summary_notice(self, notice, *, excluded=()):
        if self.summary_event(notice) is not None or self.suppressed_except(notice, excluded):
            return False
        if notice.values["chat_message_id"]:
            try:
                owner = self.require_agent(notice.values["agent_id"])
                view = self.manager._messaging.view(owner, notice.values["chat_message_id"])
                return view.values["view_kind"] == "live" and not view.values["deleted"] and self.manager._messaging.summary(view, self.manager._records.index, include_preview=False).unread
            except PermissionError:
                return False
        if notice.values["mail_id"]:
            mail = next((mail for mail in self.manager._inbox.list(notice.values["agent_id"], unread_only=False)
                         if mail.message_id == notice.values["mail_id"]), None)
            return (mail is not None and mail.read_at is None
                and (mail.message_type != "governance_choice_request" or self.manager._governance.is_outstanding(
                    notice.values["agent_id"], mail.payload.get("case_id"))))
        return self.manager._messaging.can_present(notice)

    def summary_counts(self, notice):
        counts = Counter()
        for identifier in self.coverage_index()[1].get(notice.values["notification_id"], ()):
            source = self.manager._records.index[("agent_notifications", (identifier,))]
            if self.eligible_summary_notice(source):
                counts[self.summary_source(source)] += 1
        return [{"source_kind": kind, "source_id": source, "count": count}
                for (kind, source), count in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1] or ""))]

    def suppression_summary_records(self, preference):
        covered = self.covered_notice_ids()
        presented = {row.values["notification_id"] for row in self.manager._records.snapshot()
            if row.table_name == "notification_claims" and row.values["status"] == "presented"}
        selected = [row for row in self.manager._records.snapshot() if row.table_name == "agent_notifications"
            and row.values["agent_id"] == preference.values["agent_id"]
            and row.values["notification_id"] not in covered | presented and self.preference_matches(preference, row)
            and self.eligible_summary_notice(row, excluded=(preference.values["preference_id"],))]
        if not selected:
            return (), (), ()
        owner = preference.values["agent_id"]
        event = self.manager._memory.record_event("notification_summary", agent=self.require_agent(owner),
            payload={"preference_id": preference.values["preference_id"]}, persist=False, inherit_context=False, staged=True)
        notice_id = f"SUMMARY-{preference.values['preference_id']}"
        marker = self.manager._records.index.get(("agent_activities", (owner,)))
        arrival = marker.values["arrival_generation"] + 1 if marker else 1
        session = self.sessions.get(owner) or Session(owner, identifier("ADMISSION"), self.generation, active=False, intent="idle")
        rows = [capture(self.manager, "agent_notifications", notification_id=notice_id, agent_id=owner,
            source_kind="system_event", system_event_id=event.event_id, classification="ordinary",
            deduplication_key=f"suppression-ended:{preference.values['preference_id']}",
            arrival_generation=arrival, created_at=self.clock.wall_time()), self.marker(session, arrival_generation=arrival)]
        rows.extend(capture(self.manager, "notification_summary_items", summary_id=notice_id,
            notification_id=row.values["notification_id"]) for row in selected)
        return rows, (notice_id,), (event.event_id,)
