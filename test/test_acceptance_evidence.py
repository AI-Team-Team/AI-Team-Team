"""Acceptance bookkeeping cannot turn skips or fixture errors into success."""

import io
import tempfile
import unittest
from pathlib import Path

from scripts.acceptance.evidence import source_digest
from scripts.acceptance.results import EvidenceResult
from scripts.acceptance.matrix import load_checks, project
from scripts.acceptance.summary import summarize
from test.acceptance_reports import run_reports, write_reports


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_missing_current_ledger_cannot_fall_back_to_an_archive(self):
        with tempfile.TemporaryDirectory(prefix="att-missing-ledger-") as directory:
            root = Path(directory)
            constants = root / "src/ai_team_team/database/persistence/constants.py"
            constants.parent.mkdir(parents=True)
            constants.write_text('STATE_SCHEMA_VERSION = "16"\n', encoding="utf-8")
            historical = root / "docs_archive/dev/autonomous_activity/verification_cases.json"
            historical.parent.mkdir(parents=True)
            historical.write_text('{"checks": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "current ATT verification ledger is missing"):
                load_checks(root)

    def test_summary_rejects_stale_sources_mixed_environments_and_string_success(self):
        root = Path(__file__).resolve().parents[1]
        checks = load_checks(root)
        selectors = sorted({selector for check in checks for selector in check["selectors"]})
        with tempfile.TemporaryDirectory(prefix="att-acceptance-summary-") as directory:
            paths, reports = run_reports(root, Path(directory), selectors)
            identity = reports[0]["environment"]
            def evaluate():
                write_reports(paths, reports)
                return summarize(root, paths)
            self.assertTrue(evaluate()["passed"])
            reports[0] = {**reports[0], "passed": "false"}
            self.assertFalse(evaluate()["passed"])
            reports[0] = {**reports[0], "passed": True, "environment": {**identity, "source_digest": "stale"}}
            self.assertFalse(evaluate()["passed"])
            reports[0] = {**reports[0], "environment": {**identity, "platform": "different"}}
            self.assertFalse(evaluate()["passed"])

    def test_current_ledger_resolves_real_methods_and_covers_all_formal_areas(self):
        checks = load_checks(Path(__file__).resolve().parents[1])
        self.assertGreater(len(checks), 100)
        self.assertTrue(all(check["selectors"] for check in checks))

    def test_existing_selectors_and_unexecuted_checks_are_separate_evidence(self):
        checks = [{"id": "ONE", "coverage": "covered", "selectors": ["one", "two"]}]
        reports = [{"cases": [{"selector": "one", "status": "passed"}]}]
        self.assertEqual(project(checks, reports)[0]["execution"], "not_run")
        reports.append({"cases": [{"selector": "two", "status": "skipped"}]})
        self.assertEqual(project(checks, reports)[0]["execution"], "failed")
        reports[-1]["cases"][0]["status"] = "passed"
        self.assertEqual(project(checks, reports)[0]["execution"], "passed")

    def execute(self, case):
        return unittest.TextTestRunner(stream=io.StringIO(), resultclass=EvidenceResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(case))

    def test_class_fixture_errors_have_recorded_test_identity_without_payloads(self):
        class BrokenFixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("PRIVATE_FIXTURE_PAYLOAD")

            def test_body(self):
                self.fail("The broken fixture cannot run this body.")
        result = self.execute(BrokenFixture)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.cases[0]["status"], "error")
        self.assertEqual(result.cases[0]["error_type"], "RuntimeError")
        self.assertNotIn("PRIVATE_FIXTURE_PAYLOAD", str(result.cases))

    def test_subtest_failure_and_skip_cannot_be_overwritten_by_parent_success(self):
        class MixedSubtests(unittest.TestCase):
            def test_failed_subtest(self):
                with self.subTest(seed=1):
                    self.fail("PRIVATE_ASSERTION_PAYLOAD")

            def test_skipped_subtest(self):
                with self.subTest(seed=2):
                    self.skipTest("PRIVATE_SKIP_PAYLOAD")
        result = self.execute(MixedSubtests)
        self.assertEqual([item["status"] for item in result.cases], ["failed", "skipped"])
        self.assertNotIn("PRIVATE_", str(result.cases))

    def test_result_artifacts_do_not_change_source_identity_but_source_edits_do(self):
        with tempfile.TemporaryDirectory(prefix="att-evidence-") as directory:
            root = Path(directory)
            (root / "src").mkdir()
            source = root / "src/example.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            before = source_digest(root)
            (root / "result.json").write_text('{"passed":true}', encoding="utf-8")
            self.assertEqual(source_digest(root), before)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(source_digest(root), before)
            for name in ("test/fixture.json", "docs/user/API_Reference.md", "README.md",
                         "docs/dev/verification/verification_cases.json"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                before = source_digest(root)
                path.write_text("Test input version one.\n", encoding="utf-8")
                self.assertNotEqual(source_digest(root), before, name)
                before = source_digest(root)
                path.write_text("Test input version two.\n", encoding="utf-8")
                self.assertNotEqual(source_digest(root), before, name)
            for name in ("docs_archive/dev/autonomous_activity/Phase_8.md",
                         "docs_archive/dev/autonomous_activity/acceptance/result.json",
                         "src/__pycache__/generated.pyc", "src/package.egg-info/SOURCES.txt"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                before = source_digest(root)
                path.write_text("Generated evidence or metadata.\n", encoding="utf-8")
                self.assertEqual(source_digest(root), before, name)
