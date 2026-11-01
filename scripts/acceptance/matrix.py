"""Resolve declared evidence without importing test modules or inferring coverage."""

import ast
import json
from pathlib import Path


LEDGER = Path("docs/dev/autonomous_activity/verification_cases.json")


def load_checks(root):
    path = root / LEDGER
    if not path.exists():
        return []  # A pinned baseline predating this evidence ledger.
    data = json.loads(path.read_text(encoding="utf-8"))
    constants = ast.parse((root / "src/ai_team_team/database/persistence/constants.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in constants.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "STATE_SCHEMA_VERSION" for target in node.targets))
    if data["schema"] != version:
        raise ValueError("Verification evidence targets a different persistence schema.")
    checks = data["checks"]
    identifiers = set()
    for check in checks:
        if check["id"] in identifiers or check["coverage"] not in {"covered", "partial", "missing"}:
            raise ValueError("Invalid or duplicate verification identity.")
        identifiers.add(check["id"])
        if check["coverage"] == "covered" and not check["selectors"]:
            raise ValueError("Covered requirements need concrete test selectors.")
        for selector in check["selectors"]:
            module, owner, method = selector.rsplit(".", 2)
            source = root.joinpath(*module.split(".")).with_suffix(".py")
            if not source.is_file():
                raise ValueError(f"Verification module is missing: {module}.")
            classes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
                       if isinstance(node, ast.ClassDef) and node.name == owner]
            if len(classes) != 1 or not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method and method.startswith("test_") for node in classes[0].body):
                raise ValueError(f"Verification method is missing: {selector}.")
    if not checks:
        raise ValueError("The current verification ledger is empty.")
    formal = root / data["source_matrix"]
    areas = [line.split("|")[1].strip() for line in formal.read_text(encoding="utf-8").splitlines()
             if line.startswith("| ") and not line.startswith(("| Area ", "| ---"))]
    if set(areas) != {check["area"] for check in checks}:
        raise ValueError("Verification evidence must account for every formal area.")
    return checks


def project(checks, reports):
    outcomes = {}
    for report in reports:
        for case in report.get("cases", ()):
            outcomes.setdefault(case["selector"], []).append(case["status"])
    rows = []
    for check in checks:
        statuses = [outcomes.get(selector, ["not_run"]) for selector in check["selectors"]]
        flattened = [status for group in statuses for status in group]
        execution = "passed" if flattened and set(flattened) == {"passed"} else (
            "failed" if any(status not in {"passed", "not_run"} for status in flattened) else "not_run")
        rows.append({"id": check["id"], "coverage": check["coverage"], "execution": execution})
    return rows
