"""Functional organization keeps every runtime scenario in ordinary discovery."""

import unittest
from collections import Counter

from ._support import ROOT


class DocumentationOrganizationTests(unittest.TestCase):
    def test_default_discovery_contains_each_runtime_scenario_once(self):
        expected = {
            "test_a_plain_answer_continues_activity_without_publication",
            "test_shared_person_admission_coalesces_across_team_scopes",
            "test_an_idle_owner_receives_mail_without_a_forced_reply_or_read",
            "test_arrival_during_a_tool_wait_enters_the_immediate_next_valid_frame",
            "test_threshold_releases_only_the_wait_and_produces_one_native_observation",
        }
        suite = unittest.TestLoader().discover(str(ROOT / "test"), top_level_dir=str(ROOT))

        def methods(tests):
            for test in tests:
                if isinstance(test, unittest.TestSuite):
                    yield from methods(test)
                else:
                    yield test.id().rsplit(".", 1)[-1]

        actual = Counter(name for name in methods(suite) if name in expected)
        self.assertEqual(actual, Counter({name: 1 for name in expected}))
