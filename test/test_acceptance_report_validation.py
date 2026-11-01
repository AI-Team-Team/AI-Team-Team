"""Contradictory and incomplete run reports cannot claim aggregate success."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.acceptance.matrix import load_checks
from scripts.acceptance.summary import summarize
from test.acceptance_reports import coverage_artifact, run_reports, write_reports


class ReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        directory = tempfile.TemporaryDirectory(prefix="att-report-validation-")
        self.addCleanup(directory.cleanup)
        selectors = sorted({selector for check in load_checks(self.root) for selector in check["selectors"]})
        self.paths, self.reports = run_reports(self.root, Path(directory.name), selectors)

    def evaluate(self):
        write_reports(self.paths, self.reports)
        return summarize(self.root, self.paths)

    def test_complete_measured_evidence_passes(self):
        self.assertTrue(self.evaluate()["passed"])

    def test_zero_coverage_is_rejected_even_when_flags_claim_success(self):
        coverage_artifact(self.paths[0], self.reports[0], percentage=0)
        result = self.evaluate()
        self.assertFalse(result["passed"])
        self.assertFalse(result["coverage_gate_passed"])
        self.assertTrue(result["invalid_reports"])

    def test_coverage_cannot_lower_repository_policy(self):
        coverage_artifact(self.paths[0], self.reports[0], percentage=0)
        self.reports[0]["coverage_threshold"] = 0
        self.assertFalse(self.evaluate()["passed"])

    def test_missing_nonfinite_and_boolean_metrics_are_rejected(self):
        original = copy.deepcopy(self.reports[0])
        for value in (None, float("nan"), float("inf"), True, "100", -1, 101):
            with self.subTest(value=value):
                self.reports[0] = {**copy.deepcopy(original), "coverage_percent": value}
                self.assertFalse(self.evaluate()["passed"])
        for key in ("coverage_percent", "coverage_threshold", "coverage_artifact_sha256"):
            with self.subTest(missing=key):
                self.reports[0] = copy.deepcopy(original)
                del self.reports[0][key]
                self.assertFalse(self.evaluate()["passed"])

    def test_missing_or_modified_artifact_is_rejected(self):
        artifact = self.paths[0].parent / "coverage.json"
        artifact.write_bytes(artifact.read_bytes() + b"\n")
        self.assertFalse(self.evaluate()["passed"])
        artifact.unlink()
        self.assertFalse(self.evaluate()["passed"])

    def test_report_percentage_cannot_disagree_with_measured_counts(self):
        coverage_artifact(self.paths[0], self.reports[0], percentage=0)
        self.reports[0]["coverage_percent"] = 100
        self.assertFalse(self.evaluate()["passed"])

    def test_invalid_measurement_counts_and_disabled_branches_are_rejected(self):
        artifact = self.paths[0].parent / "coverage.json"
        original = json.loads(artifact.read_text())
        for field, value in (("num_statements", 0), ("missing_lines", 9), ("covered_branches", True)):
            with self.subTest(field=field):
                data = copy.deepcopy(original)
                data["totals"][field] = value
                artifact.write_text(json.dumps(data))
                self.reports[0]["coverage_artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
                self.assertFalse(self.evaluate()["passed"])
        data = copy.deepcopy(original)
        data["meta"]["branch_coverage"] = False
        artifact.write_text(json.dumps(data))
        self.reports[0]["coverage_artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.assertFalse(self.evaluate()["passed"])

    def test_missing_statistics_and_hidden_failed_cases_cannot_pass(self):
        original = copy.deepcopy(self.reports[0])
        for key in ("tests", "elapsed_seconds", "started_at_utc", "leaks"):
            with self.subTest(missing=key):
                self.reports[0] = copy.deepcopy(original)
                del self.reports[0][key]
                self.assertFalse(self.evaluate()["passed"])
        self.reports[0] = copy.deepcopy(original)
        self.reports[0]["tests"] += 1
        self.assertFalse(self.evaluate()["passed"])
        self.reports[0]["cases"].append({"selector": "unmapped.failure", "status": "failed", "elapsed_seconds": 1})
        self.assertFalse(self.evaluate()["passed"])

    def test_malformed_reports_fail_without_crashing_aggregation(self):
        for value in (None, [], {"suite": []}, {"cases": [None]}):
            with self.subTest(value=value):
                self.reports[0] = value
                result = self.evaluate()
                self.assertFalse(result["passed"])
                self.assertTrue(result["invalid_reports"])
