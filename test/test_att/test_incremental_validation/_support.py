"""Value-only candidate graphs and a real isolated SQLite store."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import insert

from ai_team_team.database.models import AgentModel
from ai_team_team.database.persistence.receipts import CommitReceipt
from ai_team_team.database.persistence.store import DatabaseStore
from test.test_att.test_autonomous_activity_phase1._support import invocation_graph, model_request, record


OWNER = "person"


def state(records=None):
    return {"agents": [{"agent_id": OWNER, "name": "Person", "lifecycle_state": "active"}],
            "teams": [], "records": tuple(records if records is not None else (*invocation_graph(OWNER), model_request(OWNER)))}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-incremental-validation-")
        self.addCleanup(self.workspace.cleanup)
        self.path = str(Path(self.workspace.name) / "state.sqlite")
        self.store = DatabaseStore(self.path)
        self.addCleanup(self.store.close)
        with self.store.session_factory() as session:
            session.execute(insert(AgentModel).values(agent_id=OWNER, name="Person", lifecycle_state="active", state_version=1))
            session.commit()
        self.write((*invocation_graph(OWNER), model_request(OWNER)), version=1)

    def write(self, records=(), *, version=2):
        return self.store.write({"full": False, "records": tuple(records), "state_version": version,
            "links": None, "_operations": (CommitReceipt(f"operation-{version}", version, "durable", ()),)})


__all__ = ["OWNER", "StoreCase", "invocation_graph", "model_request", "record", "state"]
