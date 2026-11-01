"""Retain test identities and outcomes without serializing assertion payloads."""

import time
import math
import os
import faulthandler
from pathlib import Path
import unittest


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        self.diagnostic_stream = kwargs.pop("diagnostic_stream", None)
        self.console = kwargs.pop("console", None)
        super().__init__(*args, **kwargs)
        self.cases = []
        self.active = {}

    def _setupStdout(self):
        super()._setupStdout()
        if self.console is not None:
            # unittest brackets class/module fixtures with these hooks too.
            self.console.start_scope()

    def _restoreStdout(self):
        try:
            if self.console is not None:
                self.console.finish_scope()
        finally:
            super()._restoreStdout()

    def _note(self, test, status, detail=""):
        if self.console is not None:
            self.console.note(status, test.id(), detail)

    def startTest(self, test):
        if self.diagnostic_stream is not None:
            # Keep the diagnostic armed through IsolatedAsyncioTestCase's
            # post-result loop cleanup, resetting it when the next test starts.
            faulthandler.dump_traceback_later(180, repeat=True, file=self.diagnostic_stream)
        super().startTest(test)
        self.active[id(test)] = {
            "selector": test.id(), "status": "running", "started": time.perf_counter(),
        }
        if self.console is not None:
            self.console.started(test)

    def outcome(self, test, status, error=None):
        test = getattr(test, "test_case", test)
        record = self.active.get(id(test))
        if record is None:
            # Class/module fixture failures have no startTest/stopTest pair.
            record = {"selector": test.id(), "elapsed_seconds": 0}
            self.cases.append(record)
        if status != "passed" or record.get("status") == "running":
            record["status"] = status
        if error is not None:
            record["error_type"] = error[0].__name__
            frames, position = [], error[2]
            root = Path(os.environ.get("ATT_ACCEPTANCE_ROOT", Path.cwd())).resolve()
            while position is not None:
                path = Path(position.tb_frame.f_code.co_filename)
                name = path.resolve().relative_to(root).as_posix() if path.resolve().is_relative_to(root) else path.name
                frames.append({"file": name, "line": position.tb_lineno, "function": position.tb_frame.f_code.co_name})
                position = position.tb_next
            record["frames"] = frames

    def addSuccess(self, test):
        self.outcome(test, "passed")
        super().addSuccess(test)

    def addError(self, test, error):
        self.outcome(test, "error", error)
        super().addError(test, error)
        self._note(test, "ERROR", self.errors[-1][1])

    def addFailure(self, test, error):
        self.outcome(test, "failed", error)
        super().addFailure(test, error)
        self._note(test, "FAIL", self.failures[-1][1])

    def addSkip(self, test, reason):
        self.outcome(test, "skipped")
        super().addSkip(test, reason)
        self._note(test, "SKIP", reason)

    def addExpectedFailure(self, test, error):
        self.outcome(test, "expected_failure", error)
        super().addExpectedFailure(test, error)
        self._note(test, "EXPECTED FAILURE", self.expectedFailures[-1][1])

    def addUnexpectedSuccess(self, test):
        self.outcome(test, "unexpected_success")
        super().addUnexpectedSuccess(test)
        self._note(test, "UNEXPECTED SUCCESS")

    def addSubTest(self, test, subtest, error):
        if error is not None:
            self.outcome(test, "failed", error)
        super().addSubTest(test, subtest, error)
        if error is not None:
            failures = self.failures if issubclass(error[0], test.failureException) else self.errors
            self._note(subtest, "FAIL" if failures is self.failures else "ERROR", failures[-1][1])

    def stopTest(self, test):
        record = self.active.pop(id(test))
        record["elapsed_seconds"] = round(time.perf_counter() - record.pop("started"), 6)
        metrics = getattr(test, "acceptance_metrics", {})
        if isinstance(metrics, dict):
            record["metrics"] = {key: value for key, value in metrics.items()
                                 if isinstance(key, str) and key.isidentifier()
                                 and type(value) in (int, float) and math.isfinite(value)}
        operations = {"send", "edit", "block", "unblock", "remove", "friend"}
        trace = getattr(test, "acceptance_trace", ())
        if isinstance(trace, (list, tuple)):
            record["operation_trace"] = [list(item) for item in trace
                if isinstance(item, (tuple, list)) and len(item) == 5
                and type(item[2]) is str and item[2] in operations
                and all(type(item[index]) is int for index in (0, 1, 3, 4))]
        self.cases.append(record)
        if self.console is not None:
            self.console.finished(record)
        super().stopTest(test)

    def stopTestRun(self):
        if self.diagnostic_stream is not None:
            faulthandler.cancel_dump_traceback_later()
        super().stopTestRun()
