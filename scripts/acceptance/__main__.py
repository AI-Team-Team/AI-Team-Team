"""Run with python -m scripts.acceptance from the repository root."""

import argparse
import json
import sys
from pathlib import Path

from .runner import SUITES, execute
from .evidence import write_report
from .console import runner_error


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("The workload must be a positive integer.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True, help="Evidence directory outside the source tree.")
    parser.add_argument("--suite", choices=SUITES, default="full")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--revision", help="Pinned revision for an exported source archive without Git metadata.")
    parser.add_argument("--seeds", type=positive, default=8)
    parser.add_argument("--operations", type=positive, default=96)
    console = parser.add_mutually_exclusive_group()
    console.add_argument("-v", "--verbose", action="store_true", help="Show each test's progress on stderr; successful test output stays in the log.")
    console.add_argument("-q", "--quiet", action="store_true", help="Emit only the JSON summary; keep raw diagnostics in the external log.")
    console.add_argument("--all-output", action="store_true", help="Stream the complete test log to stderr, including successful output and full tracebacks.")
    options = parser.parse_args()
    if options.coverage and options.suite != "full":
        parser.error("The project coverage threshold applies to the full suite.")
    if options.output.resolve().is_relative_to(options.root.resolve()):
        parser.error("Keep generated acceptance evidence outside the source tree.")
    if (options.output / "unittest.log").exists() or (options.output / "result.json").exists():
        parser.error("Use a fresh output directory to retain previous run evidence.")
    try:
        code = execute(options)
    except (Exception, KeyboardInterrupt) as error:
        path = options.output.resolve() / "result.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        report.update(passed=False, status="interrupted" if isinstance(error, KeyboardInterrupt) else "runner_error",
                      runner_error_type=type(error).__name__)
        write_report(path, report)
        runner_error(error, path.parent / "unittest.log", None if options.quiet else sys.stderr)
        print(json.dumps({"passed": False, "runner_error_type": type(error).__name__}))
        code = 130 if isinstance(error, KeyboardInterrupt) else 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
