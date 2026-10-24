"""Causal ballot mail is insert-only, unlike independently mutable read receipts."""

from ai_team_team import StatePersistenceError
from ai_team_team.database.models import AgentInboxModel
from ai_team_team.database.persistence.store.records import validate_database

from ._support import OWNER, StoreCase


class PersonalMailDependencyTests(StoreCase):
    @staticmethod
    def message(**changes):
        return {"message_id": "causal-mail", "agent_id": OWNER, "message_type": "personal_instruction",
            "payload": {"text": "An immutable addressed instruction."}, "created_at": 1.0, "read_at": None, **changes}

    def write_mail(self, *, version, inbox=None, dependency=None):
        self.store.write({"full": False, "state_version": version, "links": None,
            "agent_inboxes": {} if inbox is None else {OWNER: {"messages": [inbox]}},
            "agent_inbox_dependencies": [] if dependency is None else [dependency]})

    def test_old_causal_mail_cannot_erase_newer_read_receipt(self):
        self.write_mail(version=2, inbox=self.message(read_at=2.0))
        self.write_mail(version=3, dependency=self.message())
        with self.store.session_factory() as session:
            row = session.get(AgentInboxModel, "causal-mail")
            self.assertEqual(row.read_at, 2.0)
            validate_database(session)

    def test_coalesced_authoritative_inbox_and_causal_prerequisite_insert_once(self):
        self.write_mail(version=2, inbox=self.message(read_at=2.0), dependency=self.message())
        with self.store.session_factory() as session:
            self.assertEqual(session.query(AgentInboxModel).count(), 1)
            self.assertEqual(session.get(AgentInboxModel, "causal-mail").read_at, 2.0)
            validate_database(session)

    def test_causal_identity_cannot_rebind_immutable_payload(self):
        self.write_mail(version=2, inbox=self.message())
        with self.assertRaises(StatePersistenceError):
            self.write_mail(version=3, dependency=self.message(payload={"text": "Different authority."}))
        with self.store.session_factory() as session:
            self.assertEqual(session.get(AgentInboxModel, "causal-mail").payload, self.message()["payload"])
            validate_database(session)
