"""Full console streaming preserves buffered tails and direct descriptor output."""

import io
import os
from pathlib import Path
import tempfile
import unittest

from scripts.acceptance.console import mirror_log


class FullConsoleTests(unittest.TestCase):
    def test_full_stream_drains_large_unicode_output_without_a_trailing_newline(self):
        payload = "a" * 65535 + "\U0001f600\u8bb0\u5fc6" * 20000
        with tempfile.TemporaryDirectory(prefix="att-console-stream-") as directory:
            path = Path(directory) / "unittest.log"
            console = io.StringIO()
            with path.open("w", encoding="utf-8", newline="\n") as log:
                with mirror_log(log, path, console):
                    log.write(payload)
            self.assertEqual(console.getvalue(), payload)
            self.assertEqual(path.read_text(encoding="utf-8"), payload)

    def test_stream_drains_descriptor_writes_when_the_body_raises(self):
        with tempfile.TemporaryDirectory(prefix="att-console-stream-") as directory:
            path = Path(directory) / "unittest.log"
            console = io.StringIO()
            with path.open("w", encoding="utf-8", newline="\n") as log:
                with self.assertRaisesRegex(ValueError, "Synthetic body failure"):
                    with mirror_log(log, path, console):
                        os.write(log.fileno(), b"DESCRIPTOR_OUTPUT")
                        raise ValueError("Synthetic body failure")
            self.assertEqual(console.getvalue(), "DESCRIPTOR_OUTPUT")

    def test_console_write_errors_are_propagated(self):
        class BrokenConsole:
            def write(self, text):
                raise OSError("Synthetic console failure")

        with tempfile.TemporaryDirectory(prefix="att-console-stream-") as directory:
            path = Path(directory) / "unittest.log"
            with path.open("w", encoding="utf-8", newline="\n") as log:
                with self.assertRaisesRegex(OSError, "Synthetic console failure"):
                    with mirror_log(log, path, BrokenConsole()):
                        log.write("RETAINED_OUTPUT")
            self.assertEqual(path.read_text(encoding="utf-8"), "RETAINED_OUTPUT")
