"""Combine full, frozen, and extended evidence for the same source inputs."""

import argparse
import json
from pathlib import Path

from .evidence import source_digest, write_report
from .matrix import load_checks, project
from .report_validation import coverage_threshold, validate_report


def summarize(root, paths):
    reports, invalid = [], []
    threshold = coverage_threshold(root)
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            invalid.append({"report": str(path), "reasons": [f"Cannot read report: {type(error).__name__}."]})
            continue
        errors = validate_report(report, path, threshold)
        if errors:
            invalid.append({"report": str(path), "reasons": errors})
        reports.append((report, not errors))
    current = source_digest(root)
    identities = [report.get("environment", {}) if isinstance(report, dict) else {} for report, _ in reports]
    compatible = bool(reports) and all(isinstance(identity, dict) and identity.get("source_digest") == current for identity in identities)
    environments = {json.dumps({key: identity.get(key) for key in ("python", "platform", "machine", "sqlite", "packages")},
        sort_keys=True) for identity in identities if isinstance(identity, dict)}
    environment_compatible = len(environments) == 1
    outcomes = [{"cases": [case for case in report["cases"] if isinstance(case, dict)
                 and isinstance(case.get("selector"), str) and isinstance(case.get("status"), str)]}
                for report, _ in reports if isinstance(report, dict) and isinstance(report.get("cases"), list)]
    checks = project(load_checks(root), outcomes)
    suites = {report["suite"] for report, accepted in reports if accepted}
    coverage = any(report.get("coverage") is True for report, accepted in reports if accepted)
    passed = bool(compatible and environment_compatible and checks and {"full", "frozen", "extended"} <= suites and coverage
              and not invalid
              and all(row["coverage"] == "covered" and row["execution"] == "passed" for row in checks))
    return {"passed": passed, "source_digest": current, "source_compatible": compatible,
            "environment_compatible": environment_compatible,
            "required_suites": sorted(suites), "coverage_gate_passed": coverage,
            "checks": checks, "invalid_reports": invalid,
            "platform_scope": "Only the environments recorded in the supplied runs."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("reports", type=Path, nargs="+")
    options = parser.parse_args()
    report = summarize(options.root.resolve(), options.reports)
    write_report(options.output, report)
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
