"""Display selected failures or the complete, unfiltered evidence log."""

import codecs
from contextlib import contextmanager
import threading
import traceback

from .capture import flush_output


@contextmanager
def mirror_log(log_stream, log_path, destination):
    """Stream all log bytes, including direct descriptor writes, to the console."""
    if destination is None:
        yield
        return
    stopped = threading.Event()
    final_size, errors = [None], []

    def follow():
        try:
            decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
            with log_path.open("rb") as source:
                while True:
                    finished = stopped.is_set()
                    limit = final_size[0] if finished else None
                    remaining = None if limit is None else max(0, limit - source.tell())
                    if remaining == 0:
                        break
                    chunk = source.read(65536 if remaining is None else min(65536, remaining))
                    if chunk:
                        destination.write(decoder.decode(chunk))
                        destination.flush()
                    elif finished:
                        if remaining:
                            raise OSError("The acceptance log ended before its final recorded position.")
                        break
                    else:
                        stopped.wait(0.05)
            destination.write(decoder.decode(b"", final=True))
            destination.flush()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=follow, name="att-acceptance-console", daemon=True)
    worker.start()
    try:
        yield
    finally:
        try:
            log_stream.flush()
        finally:
            try:
                final_size[0] = log_path.stat().st_size
            finally:
                stopped.set()
                worker.join()
        if errors:
            raise errors[0]


class AcceptanceConsole:
    def __init__(self, log_stream, log_path, stream, *, verbose=False, failure_details=True):
        self.log_stream = log_stream
        self.log_path = log_path
        self.stream = stream
        self.verbose = verbose
        self.failure_details = failure_details
        self.scopes = []

    def start_scope(self):
        if self.stream is not None and self.failure_details:
            flush_output()
            self.log_stream.flush()
            self.scopes.append((self.log_stream.tell(), []))

    def note(self, status, selector, detail=""):
        if self.stream is None or not self.failure_details:
            return
        issue = (status, selector, detail)
        if self.scopes:
            self.scopes[-1][1].append(issue)
        else:
            self._show([issue])

    def finish_scope(self):
        if self.stream is None or not self.scopes:
            return
        flush_output()
        self.log_stream.flush()
        start, issues = self.scopes.pop()
        if issues:
            self._show(issues, start, self.log_stream.tell())

    def started(self, test):
        if self.stream is not None and self.verbose:
            self.stream.write(f"{test.id()} ... ")
            self.stream.flush()

    def finished(self, record):
        if self.stream is not None and self.verbose:
            self.stream.write(f"{record['status']} ({record['elapsed_seconds']:.3f}s)\n")
            self.stream.flush()

    def _show(self, issues, start=None, end=None):
        self.stream.write("\n" + "=" * 70 + "\n")
        for status, selector, _ in issues:
            self.stream.write(f"{status}: {selector}\n")
        if start is not None and end > start:
            self.stream.write("\nCaptured output:\n")
            # Read a separate handle so reporting cannot move the writer's
            # position, and stream large failures without buffering pass logs.
            decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
            with self.log_path.open("rb") as log:
                log.seek(start)
                remaining = end - start
                while remaining:
                    chunk = log.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    self.stream.write(decoder.decode(chunk))
            self.stream.write(decoder.decode(b"", final=True) + "\n")
        for status, selector, detail in issues:
            if detail:
                self.stream.write(f"\n{status}: {selector}\n{detail.rstrip()}\n")
        self.stream.write("=" * 70 + "\n")
        self.stream.flush()

    def rejected(self, report):
        if self.stream is None:
            return
        reasons = []
        if not report["successful"]:
            reasons.append("Tests failed or errored.")
        if not report["tests"]:
            reasons.append("No tests were executed.")
        if report["skips"]:
            reasons.append(f"Skipped tests: {report['skips']}.")
        if any(case["status"] != "passed" for case in report["cases"]):
            reasons.append("Non-passing test outcomes were recorded.")
        if not report["source_unchanged"]:
            reasons.append("Source inputs changed during the run.")
        if report["root_doclib_exists"]:
            reasons.append("Project-root .att_doc_libs remains after tests.")
        for marker, count in report["leaks"].items():
            if count:
                reasons.append(f"Resource diagnostic {marker!r}: {count}.")
        if report.get("coverage_percent", 100) < report.get("coverage_threshold", 0):
            reasons.append("Coverage is below the configured threshold.")
        self.stream.write("Acceptance failed:\n" + "\n".join(f"- {reason}" for reason in reasons))
        self.stream.write(f"\nFull log: {self.log_path}\n")
        self.stream.flush()


def runner_error(error, log_path, stream):
    """Keep raw exception details in the log and optional human stderr only."""
    detail = "".join(traceback.format_exception(error))
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write("\nAcceptance runner error:\n" + detail)
    if stream is not None:
        stream.write("Acceptance runner error:\n" + detail)
        stream.write(f"Full log: {log_path}\n")
        stream.flush()
