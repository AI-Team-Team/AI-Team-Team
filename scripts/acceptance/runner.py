"""Run actual unittest discovery against a pinned source origin."""

import faulthandler
import importlib
import hashlib
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from functools import partial

from .evidence import environment, source_digest, write_report
from .results import EvidenceResult
from .matrix import load_checks, project
from .console import AcceptanceConsole, mirror_log
from .capture import capture_output, preserved_stderr
from .diagnostics import counts as diagnostic_counts, observe_diagnostics


SUITES = {
    "full": ("test", "test*.py"),
    "frozen": ("test/test_att/test_autonomous_activity_phase0", "spec_*.py"),
    "extended": ("test/reliability", "stress_*.py"),
}


def execute(options):
    with preserved_stderr() as console_stream:
        return _execute(options, console_stream)


def _execute(options, destination):
    root = options.root.resolve()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"suite": options.suite, "coverage": options.coverage,
              "passed": False, "status": "running",
              "console_mode": "all" if options.all_output else "quiet" if options.quiet else "verbose" if options.verbose else "failures",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "environment": environment(root, options.revision),
              "stress_seeds": options.seeds, "stress_operations": options.operations}
    write_report(output / "result.json", report)
    # Subprocess fixtures inherit the same source origin as the parent.
    os.environ["PYTHONPATH"] = str(root / "src") + os.pathsep + str(root)
    os.environ["ATT_STRESS_SEEDS"] = str(options.seeds)
    os.environ["ATT_STRESS_OPERATIONS"] = str(options.operations)
    os.environ["ATT_ACCEPTANCE_ROOT"] = str(root)
    sys.path[:0] = [str(root / "src"), str(root), str(root / "test")]
    os.chdir(root)
    log = output / "unittest.log"
    coverage_run = None
    console_stream = None if options.quiet else destination
    started = time.perf_counter()
    with (
        log.open("w", encoding="utf-8", buffering=1, newline="\n") as stream,
        mirror_log(stream, log, console_stream if options.all_output else None),
        capture_output(stream),
        observe_diagnostics(output) as diagnostic_directory,
    ):
        console = AcceptanceConsole(stream, log, console_stream, verbose=options.verbose,
                                    failure_details=not options.all_output)
        # Diagnostics never cancel an accepted commit or change runtime policy.
        faulthandler.dump_traceback_later(180, repeat=True, file=stream)
        if options.coverage:
            import coverage
            coverage_run = coverage.Coverage(
                config_file=str(root / "pyproject.toml"), data_file=str(output / ".coverage"),
                branch=True, source=["ai_team_team"],
            )
            coverage_run.start()
        try:
            package = importlib.import_module("ai_team_team")
            if not Path(package.__file__).resolve().is_relative_to(root / "src"):
                raise RuntimeError("Acceptance imported a different source origin.")
            checks = load_checks(root)
            directory, pattern = SUITES[options.suite]
            suite = unittest.defaultTestLoader.discover(str(root / directory), pattern=pattern, top_level_dir=str(root))
            result = unittest.TextTestRunner(stream=stream, verbosity=2, warnings="default",
                resultclass=partial(EvidenceResult, diagnostic_stream=stream, console=console)).run(suite)
        finally:
            faulthandler.cancel_dump_traceback_later()
            if coverage_run is not None:
                coverage_run.stop()
                coverage_run.save()
        report.update(tests=result.testsRun, cases=result.cases,
                      successful=result.wasSuccessful(), skips=len(result.skipped))
        if coverage_run is not None:
            percentage = coverage_run.report(file=stream)
            coverage_run.json_report(outfile=str(output / "coverage.json"))
            coverage_run.xml_report(outfile=str(output / "coverage.xml"))
            coverage_run.html_report(directory=str(output / "htmlcov"))
            report["coverage_percent"] = percentage
            report["coverage_threshold"] = coverage_run.get_option("report:fail_under")
            report["coverage_artifact_sha256"] = hashlib.sha256((output / "coverage.json").read_bytes()).hexdigest()
    report["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    report["status"] = "completed"
    report["verification"] = project(checks, [report])
    report["source_unchanged"] = source_digest(root) == report["environment"]["source_digest"]
    report["root_doclib_exists"] = (root / ".att_doc_libs").exists()
    report["leaks"] = diagnostic_counts(diagnostic_directory)
    report["passed"] = bool(
        report["successful"] and report["tests"] and not report["skips"]
        and all(case["status"] == "passed" for case in result.cases)
        and report["source_unchanged"] and not report["root_doclib_exists"]
        and not any(report["leaks"].values())
        and report.get("coverage_percent", 100) >= report.get("coverage_threshold", 0)
    )
    write_report(output / "result.json", report)
    if not report["passed"]:
        console.rejected(report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"cases", "environment"}}, sort_keys=True))
    return 0 if report["passed"] else 1
