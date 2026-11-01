"""Validate complete run evidence and measured coverage before aggregation."""

from datetime import datetime
import hashlib
import json
import math
import tomllib

from .diagnostics import KINDS
from .evidence import PACKAGES


def number(value, *, maximum=None):
    try:
        return (type(value) in (int, float) and math.isfinite(value) and value >= 0
                and (maximum is None or value <= maximum))
    except OverflowError:
        return False


def coverage_threshold(root):
    with (root / "pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)
    value = configuration.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under", 0)
    if not number(value, maximum=100):
        raise ValueError("The configured coverage threshold must be between zero and 100.")
    return value


def validate_coverage(report, path, threshold):
    errors = []
    if report.get("suite") != "full":
        errors.append("Coverage evidence must come from the full suite.")
    percentage, applied = report.get("coverage_percent"), report.get("coverage_threshold")
    if not number(percentage, maximum=100):
        errors.append("A finite coverage percentage is required.")
    elif percentage < threshold:
        errors.append("Measured coverage is below the repository threshold.")
    if not number(applied, maximum=100) or applied != threshold:
        errors.append("The applied coverage threshold differs from repository policy.")
    artifact = path.parent / "coverage.json"
    try:
        content = artifact.read_bytes()
        measurement = json.loads(content)
        totals = measurement["totals"]
        values = {key: totals[key] for key in ("num_statements", "covered_lines", "missing_lines",
                  "num_branches", "covered_branches", "missing_branches")}
        if any(type(value) is not int or value < 0 for value in values.values()):
            raise ValueError("Coverage counts must be nonnegative integers.")
        if (values["num_statements"] == 0 or not isinstance(measurement.get("files"), dict)
                or not measurement["files"]):
            raise ValueError("Coverage must measure nonempty source files.")
        if measurement["meta"].get("branch_coverage") is not True:
            raise ValueError("Branch measurement must be enabled.")
        if (values["covered_lines"] + values["missing_lines"] != values["num_statements"]
                or values["covered_branches"] + values["missing_branches"] != values["num_branches"]):
            raise ValueError("Coverage counts do not reconcile.")
        measured = totals["percent_covered"]
        calculated = 100 * (values["covered_lines"] + values["covered_branches"]) / (
            values["num_statements"] + values["num_branches"])
        if not number(measured, maximum=100) or not math.isclose(measured, calculated, abs_tol=1e-7):
            raise ValueError("The coverage percentage disagrees with its measured counts.")
        if not number(percentage, maximum=100) or not math.isclose(percentage, measured, abs_tol=1e-7):
            raise ValueError("The run percentage disagrees with coverage.json.")
        if report.get("coverage_artifact_sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("The coverage artifact hash is missing or does not match.")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        errors.append("Complete, consistent coverage.json evidence and its recorded hash are required.")
    return errors


def validate_report(report, path, threshold):
    if not isinstance(report, dict):
        return ["The run report must be an object."]
    errors = []
    for key in ("passed", "successful", "source_unchanged"):
        if report.get(key) is not True:
            errors.append(f"{key} must be the literal boolean true.")
    if report.get("status") != "completed" or report.get("root_doclib_exists") is not False:
        errors.append("The run must be complete with no project-root DocLib.")
    if not isinstance(report.get("suite"), str) or report["suite"] not in {"full", "frozen", "extended"}:
        errors.append("Unknown or missing suite identity.")
    tests, cases = report.get("tests"), report.get("cases")
    if type(tests) is not int or tests <= 0 or not isinstance(cases, list) or len(cases) != tests:
        errors.append("Positive test counts must match the complete per-test evidence.")
    if not isinstance(cases, list) or any(
            not isinstance(case, dict) or not isinstance(case.get("selector"), str) or not case["selector"]
            or case.get("status") != "passed" or not number(case.get("elapsed_seconds")) for case in cases):
        errors.append("Every test needs an identity, passing outcome, and finite duration.")
    if type(report.get("skips")) is not int or report["skips"] != 0:
        errors.append("Skipped tests cannot pass acceptance.")
    leaks = report.get("leaks")
    if (not isinstance(leaks, dict) or set(leaks) != set(KINDS)
            or any(type(value) is not int or value != 0 for value in leaks.values())):
        errors.append("All diagnostic counters must be present and zero.")
    if not number(report.get("elapsed_seconds")):
        errors.append("A finite run duration is required.")
    try:
        started = datetime.fromisoformat(report["started_at_utc"])
        if started.tzinfo is None:
            raise ValueError("A timezone is required.")
    except (KeyError, TypeError, ValueError):
        errors.append("A timestamp with a timezone is required.")
    environment = report.get("environment")
    if (not isinstance(environment, dict)
            or any(not isinstance(environment.get(key), str) or not environment[key]
                   for key in ("source_digest", "python", "platform", "machine", "sqlite"))
            or not isinstance(environment.get("packages"), dict)
            or any(not isinstance(environment["packages"].get(key), str) or not environment["packages"][key]
                   for key in PACKAGES)):
        errors.append("Complete source and environment identity is required.")
    if type(report.get("coverage")) is not bool:
        errors.append("Coverage mode must be a literal boolean.")
    elif report["coverage"]:
        errors.extend(validate_coverage(report, path, threshold))
    elif any(key in report for key in ("coverage_percent", "coverage_threshold", "coverage_artifact_sha256")):
        errors.append("Coverage metrics require an instrumented full run.")
    return errors
