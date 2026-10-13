"""Every common-service profile uses the same dispatch/outcome evidence rules."""

import sqlite3
import unittest
from contextlib import closing

from ai_team_team import StateRestoreError
from ai_team_team.database.persistence.records import DomainRecord, freeze, thaw

from ._request_support import install_request_sources, request_profiles
from ._support import make_manager


DISPATCHES = ("unsent", "sent", "confirmed_unsent", "unknown_sent")
OUTCOMES = ("pending", "completed", "failed", "cancelled", "uncertain")
VALID_PAIRS = {(dispatch, outcome) for dispatch in ("sent", "unknown_sent") for outcome in OUTCOMES}
VALID_PAIRS.update({("unsent", "pending"), ("confirmed_unsent", "failed"), ("confirmed_unsent", "cancelled")})


class ModelRequestStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_pairs_fail_before_domain_acceptance_for_every_profile(self):
        manager, _, client = make_manager(self, volatile=True)
        await install_request_sources(manager)
        before, version = manager._records.snapshot(), manager._state_version
        for request in request_profiles(manager.root_ai.agent_id):
            for dispatch in DISPATCHES:
                for outcome in OUTCOMES:
                    if (dispatch, outcome) in VALID_PAIRS:
                        continue
                    with self.subTest(profile=request.table_name, dispatch=dispatch, outcome=outcome):
                        values = {**thaw(request.values), "dispatch_state": dispatch, "outcome": outcome}
                        with self.assertRaisesRegex(ValueError, "dispatch/outcome combination"):
                            DomainRecord.capture(request.table_name, values)
                        # A direct dataclass construction is not an authority
                        # bypass: the service recaptures accepted input values.
                        with self.assertRaisesRegex(ValueError, "dispatch/outcome combination"):
                            await manager._records.commit((DomainRecord(request.table_name, freeze(values)),))
                        self.assertEqual(manager._records.snapshot(), before)
                        self.assertEqual(manager._state_version, version)
        self.assertEqual(client.requests, [])

    async def test_valid_pairs_commit_and_restore_for_every_profile(self):
        manager, path, client = make_manager(self)
        await install_request_sources(manager)
        records = []
        for request in request_profiles(manager.root_ai.agent_id):
            key = "model_request_id" if request.table_name == "model_requests" else "request_id"
            for index, (dispatch, outcome) in enumerate(sorted(VALID_PAIRS), 1):
                values = thaw(request.values)
                values.update({key: f"{request.table_name}-{index}", "dispatch_state": dispatch,
                               "outcome": outcome, "attempt_index": index,
                               "dispatched_at": 2.0 if dispatch in {"sent", "unknown_sent"} else None})
                records.append(DomainRecord.capture(request.table_name, values))
        await manager._records.commit(records)
        await manager.save_state()
        await manager.load_state(path)
        for record in records:
            self.assertEqual(manager._records.index[record.identity], record)
        self.assertEqual(client.requests, [])

    async def test_corrupt_pairs_are_rejected_before_restore_publication(self):
        for profile in ("model_requests", "audit_model_requests", "memory_index_requests"):
            with self.subTest(profile=profile):
                manager, path, client = make_manager(self)
                await install_request_sources(manager)
                await manager._records.commit(request_profiles(manager.root_ai.agent_id))
                root = manager.root_ai
                library = manager.libraries[root.private_doc_library_id]
                library.write_file("original.txt", "unchanged")
                await manager.save_state()
                with closing(sqlite3.connect(path)) as database:
                    database.execute(f'UPDATE "{profile}" SET outcome=\'completed\' WHERE dispatch_state=\'unsent\'')
                    database.commit()
                with self.assertRaisesRegex(StateRestoreError, "dispatch/outcome combination"):
                    await manager.load_state(path)
                self.assertIs(manager.root_ai, root)
                self.assertEqual(library.read_text("original.txt"), "unchanged")
                self.assertFalse(manager._resources.blocked)
                self.assertEqual(client.requests, [])

    async def test_bad_request_does_not_leak_a_token_reservation(self):
        manager, _, client = make_manager(self, volatile=True)
        manager.config.model_token_limits["fixture"] = 100
        await install_request_sources(manager)
        for request in request_profiles(manager.root_ai.agent_id):
            with self.subTest(profile=request.table_name):
                values = {**thaw(request.values), "outcome": "completed"}
                with self.assertRaisesRegex(ValueError, "dispatch/outcome combination"):
                    await manager.token_budget.reserve_request(DomainRecord(request.table_name, freeze(values)), 10, 20)
                self.assertEqual(manager.token_budget.available("fixture"), 100)
                self.assertFalse(manager.token_budget.has_active_reservations())
                self.assertFalse(any(row.table_name == "model_token_claims" for row in manager._records.snapshot()))
        self.assertEqual(client.requests, [])
