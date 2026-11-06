"""Synthetic report inputs for validator tests, not ATT execution evidence."""

import copy
import hashlib
import json

from scripts.acceptance.diagnostics import KINDS
from scripts.acceptance.evidence import environment
from scripts.acceptance.report_validation import coverage_threshold


def coverage_artifact(path, report, *, percentage=100):
    totals = {"num_statements": 1, "covered_lines": int(percentage == 100),
              "missing_lines": int(percentage != 100), "num_branches": 2,
              "covered_branches": 2 * int(percentage == 100),
              "missing_branches": 2 * int(percentage != 100), "percent_covered": percentage}
    artifact = {"meta": {"branch_coverage": True}, "totals": totals,
                "files": {"src/ai_team_team/__init__.py": {"summary": totals}}}
    destination = path.parent / "coverage.json"
    destination.write_text(json.dumps(artifact), encoding="utf-8")
    report["coverage_artifact_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    report["coverage_percent"] = percentage


def run_reports(root, directory, selectors):
    base = {"passed": True, "successful": True, "status": "completed", "source_unchanged": True,
            "root_doclib_exists": False, "skips": 0, "tests": len(selectors),
            "leaks": dict.fromkeys(KINDS, 0), "elapsed_seconds": 1.0,
            "started_at_utc": "2026-10-30T00:00:00+00:00", "environment": environment(root),
            "cases": [{"selector": selector, "status": "passed", "elapsed_seconds": 0.01}
                      for selector in selectors]}
    paths, reports = [], []
    for suite in ("full", "extended"):
        path = directory / suite / "result.json"
        path.parent.mkdir()
        report = {**copy.deepcopy(base), "suite": suite, "coverage": suite == "full"}
        if report["coverage"]:
            report["coverage_threshold"] = coverage_threshold(root)
            coverage_artifact(path, report)
        paths.append(path)
        reports.append(report)
    return paths, reports


def write_reports(paths, reports):
    for path, report in zip(paths, reports):
        path.write_text(json.dumps(report), encoding="utf-8")
