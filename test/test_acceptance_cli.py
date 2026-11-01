"""Real CLI runs must reject false-green suites and retain safe diagnostics."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AcceptanceCLITests(unittest.TestCase):
    def run_fixture(self, body, *arguments):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="att-acceptance-cli-") as directory:
            root = Path(directory) / "source"
            package = root / "src/ai_team_team"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("# A source-origin sentinel for this maintenance-tool test.\n", encoding="utf-8")
            tests = root / "test"
            tests.mkdir()
            (tests / "__init__.py").write_text("", encoding="utf-8")
            (tests / "test_fixture.py").write_text(body, encoding="utf-8")
            output = Path(directory) / "evidence"
            process = subprocess.run([sys.executable, "-m", "scripts.acceptance", "--root", str(root),
                "--output", str(output), *arguments], cwd=checkout, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, timeout=30)
            report = json.loads((output / "result.json").read_text(encoding="utf-8"))
            self.assertNotIn("PRIVATE_CLI_PROBE", json.dumps(report))
            self.assertNotIn("PRIVATE_CLI_PROBE", process.stdout)
            self.last_process = process
            self.last_log = (output / "unittest.log").read_text(encoding="utf-8", errors="backslashreplace")
            self.last_log_bytes = (output / "unittest.log").read_bytes()
            return process.returncode, report

    def test_successful_output_is_retained_without_console_noise(self):
        code, report = self.run_fixture("""import unittest, sys, logging
class Fixture(unittest.TestCase):
    def test_body(self):
        print('PASS_STDOUT')
        print('PASS_STDERR', file=sys.stderr)
        logging.warning('PASS_LOGGING')
""")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertEqual(self.last_process.stderr, "")
        self.assertNotIn(b"\r\n", self.last_log_bytes)
        self.assertTrue(json.loads(self.last_process.stdout)["passed"])
        for marker in ("PASS_STDOUT", "PASS_STDERR", "PASS_LOGGING"):
            self.assertIn(marker, self.last_log)
            self.assertNotIn(marker, self.last_process.stdout)

    def test_failure_shows_only_its_output_cleanup_and_traceback(self):
        code, report = self.run_fixture("""import unittest, sys
class Fixture(unittest.TestCase):
    def test_a_pass(self):
        print('PASS_OUTPUT')
    def test_b_failure(self):
        self.addCleanup(lambda: print('FAIL_CLEANUP'))
        print('FAIL_STDOUT')
        print('FAIL_STDERR', file=sys.stderr)
        self.fail('PRIVATE_CLI_PROBE')
    def tearDown(self):
        print('TEARDOWN_' + self._testMethodName)
""")
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        for marker in ("FAIL_STDOUT", "FAIL_STDERR", "FAIL_CLEANUP", "TEARDOWN_test_b_failure",
                       "Traceback (most recent call last)", "AssertionError: PRIVATE_CLI_PROBE"):
            self.assertIn(marker, self.last_process.stderr)
        self.assertNotIn("PASS_OUTPUT", self.last_process.stderr)
        self.assertNotIn("TEARDOWN_test_a_pass", self.last_process.stderr)
        self.assertIn("PASS_OUTPUT", self.last_log)
        self.assertEqual(self.last_process.stderr.count("FAIL_STDOUT"), 1)
        self.assertFalse(json.loads(self.last_process.stdout)["passed"])

    def test_verbose_progress_keeps_successful_output_in_the_log(self):
        code, report = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        print('PASS_OUTPUT')
""", "-v")
        self.assertEqual(code, 0)
        self.assertEqual(report["console_mode"], "verbose")
        self.assertIn("Fixture.test_body", self.last_process.stderr)
        self.assertIn("passed (", self.last_process.stderr)
        self.assertNotIn("PASS_OUTPUT", self.last_process.stderr)

    def test_all_output_prints_the_complete_passing_log(self):
        code, report = self.run_fixture("""import unittest, sys, os, faulthandler
class Fixture(unittest.TestCase):
    def test_body(self):
        print('PASS_STDOUT')
        print('PASS_STDERR', file=sys.stderr)
        sys.stdout.flush()
        os.write(sys.stdout.fileno(), b'DIRECT_DESCRIPTOR_OUTPUT\\n')
        faulthandler.dump_traceback(file=sys.stderr)
""", "--all-output")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertEqual(report["console_mode"], "all")
        self.assertEqual(self.last_process.stderr, self.last_log)
        for marker in ("PASS_STDOUT", "PASS_STDERR", "DIRECT_DESCRIPTOR_OUTPUT", "Current thread", "OK"):
            self.assertIn(marker, self.last_process.stderr)

    def test_all_output_includes_successful_output_and_full_failure_without_replay(self):
        code, report = self.run_fixture("""import unittest, sys
class Fixture(unittest.TestCase):
    def test_a_pass(self):
        print('PASS_OUTPUT')
    def test_b_fail(self):
        print('FAIL_OUTPUT')
        print('FAIL_STDERR', file=sys.stderr)
        self.fail('PRIVATE_CLI_PROBE')
""", "--all-output")
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        self.assertTrue(self.last_process.stderr.startswith(self.last_log))
        for marker in ("PASS_OUTPUT", "FAIL_OUTPUT", "FAIL_STDERR", "AssertionError: PRIVATE_CLI_PROBE"):
            self.assertIn(marker, self.last_process.stderr)
        self.assertEqual(self.last_process.stderr.count("PASS_OUTPUT"), 1)
        self.assertEqual(self.last_process.stderr.count("FAIL_OUTPUT"), 1)

    def test_native_standard_descriptors_and_inherited_children_share_the_log(self):
        code, report = self.run_fixture("""import os, subprocess, sys, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        os.write(1, b'NATIVE_STDOUT\\n')
        os.write(2, b'NATIVE_STDERR\\n')
        subprocess.run([sys.executable, '-c', "import os; os.write(1, b'CHILD_STDOUT\\\\n'); os.write(2, b'CHILD_STDERR\\\\n')"], check=True)
""", "--all-output")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertTrue(json.loads(self.last_process.stdout)["passed"])
        self.assertEqual(self.last_process.stderr, self.last_log)
        for marker in ("NATIVE_STDOUT", "NATIVE_STDERR", "CHILD_STDOUT", "CHILD_STDERR"):
            self.assertIn(marker, self.last_log)

    def test_buffered_native_stdio_is_flushed_before_capture_ends(self):
        code, report = self.run_fixture("""import ctypes, os, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        library = ctypes.CDLL('ucrtbase' if os.name == 'nt' else None)
        library.printf.argtypes = [ctypes.c_char_p]
        library.printf(b'BUFFERED_NATIVE_STDIO')
""", "--all-output")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertIn("BUFFERED_NATIVE_STDIO", self.last_log)
        self.assertNotIn("BUFFERED_NATIVE_STDIO", self.last_process.stdout)

    def test_binary_descriptor_output_does_not_destroy_run_results(self):
        code, report = self.run_fixture("""import os, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        os.write(1, b'BINARY_\\xff\\xfe\\n')
""", "--all-output")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertIn(b"BINARY_\xff\xfe", self.last_log_bytes)
        self.assertIn("BINARY_\\xff\\xfe", self.last_process.stderr)

    def test_diagnostic_words_in_ordinary_output_are_not_leaks(self):
        code, report = self.run_fixture("""import logging, subprocess, sys, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        print('ResourceWarning: example documentation')
        print('Task was destroyed but it is pending!')
        print('was never awaited')
        logging.getLogger('asyncio').error('Task exception was never retrieved')
        subprocess.run([sys.executable, '-c', "import sys; print('ResourceWarning: ordinary child text', file=sys.stderr)"], check=True)
""", "--all-output")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertFalse(any(report["leaks"].values()))
        self.assertIn("ResourceWarning: ordinary child text", self.last_log)

    def test_real_inherited_child_warnings_are_counted_once_in_every_mode(self):
        for arguments in ((), ("-v",), ("--quiet",), ("--all-output",)):
            with self.subTest(arguments=arguments):
                code, report = self.run_fixture("""import subprocess, sys, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        subprocess.run([sys.executable, '-Wdefault', '-c', "import warnings; warnings.warn('PRIVATE_CLI_PROBE', ResourceWarning)"], check=True)
""", *arguments)
                self.assertEqual(code, 1)
                self.assertTrue(report["successful"])
                self.assertEqual(report["leaks"]["ResourceWarning:"], 1)
                self.assertIn("ResourceWarning: PRIVATE_CLI_PROBE", self.last_log)

    def test_child_default_resource_checks_preserve_explicit_warning_filters(self):
        for arguments, expected in (([], 1), (["-Wignore::ResourceWarning"], 0)):
            with self.subTest(arguments=arguments):
                body = f"""import subprocess, sys, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        subprocess.run([sys.executable, *{arguments!r}, '-c', "import warnings; warnings.warn('PRIVATE_CLI_PROBE', ResourceWarning)"], check=True)
"""
                code, report = self.run_fixture(body)
                self.assertEqual(code, expected)
                self.assertEqual(report["leaks"]["ResourceWarning:"], expected)

    def test_clearing_test_environment_does_not_disable_parent_observation(self):
        code, report = self.run_fixture("""import os, unittest, warnings
from unittest.mock import patch
class Fixture(unittest.TestCase):
    def test_body(self):
        with patch.dict(os.environ, {}, clear=True):
            warnings.warn('PRIVATE_CLI_PROBE', ResourceWarning)
""")
        self.assertEqual(code, 1)
        self.assertTrue(report["successful"])
        self.assertEqual(report["leaks"]["ResourceWarning:"], 1)

    def test_custom_child_pythonpath_keeps_sitecustomize_and_diagnostic_observers(self):
        code, report = self.run_fixture("""import os, pathlib, subprocess, sys, tempfile, unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, 'sitecustomize.py').write_text('import builtins; builtins.acceptance_site_preserved = True')
            environment = dict(os.environ, PYTHONPATH=directory)
            program = "import builtins, warnings; assert builtins.acceptance_site_preserved; warnings.warn('PRIVATE_CLI_PROBE', ResourceWarning)"
            subprocess.run([sys.executable, '-Wdefault', '-c', program], env=environment, check=True)
            self.assertEqual(environment['PYTHONPATH'], directory)
""")
        self.assertEqual(code, 1)
        self.assertTrue(report["successful"])
        self.assertEqual(report["leaks"]["ResourceWarning:"], 1)

    def test_handled_warning_and_nested_diagnostic_scope_do_not_pollute_parent(self):
        code, report = self.run_fixture("""import pathlib, subprocess, sys, tempfile, unittest, warnings
from scripts.acceptance.diagnostics import observe_diagnostics, counts
class Fixture(unittest.TestCase):
    def test_body(self):
        with self.assertWarns(ResourceWarning):
            warnings.warn('Handled parent warning', ResourceWarning)
        with tempfile.TemporaryDirectory() as directory:
            with observe_diagnostics(pathlib.Path(directory)) as events:
                subprocess.run([sys.executable, '-Wdefault', '-c', "import warnings; warnings.warn('Handled child warning', ResourceWarning)"], check=True)
            self.assertEqual(counts(events)['ResourceWarning:'], 1)
""")
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertFalse(any(report["leaks"].values()))

    def test_real_asyncio_and_unawaited_diagnostics_are_not_string_classifications(self):
        fixtures = (
            ("import asyncio, gc\nloop = asyncio.new_event_loop()\nf = loop.create_future()\nf.set_exception(RuntimeError('Unobserved future'))\ndel f\ngc.collect()\nloop.close()", "Task exception was never retrieved"),
            ("import gc\nasync def operation(): pass\nc = operation()\ndel c\ngc.collect()", "was never awaited"),
            ("import asyncio, gc\nloop = asyncio.new_event_loop()\nt = loop.create_task(asyncio.sleep(1))\ndel t\nloop.close()\ngc.collect()", "Task was destroyed but it is pending"),
        )
        for operation, kind in fixtures:
            with self.subTest(kind=kind):
                body = "import unittest\nclass Fixture(unittest.TestCase):\n    def test_body(self):\n" + "\n".join(
                    "        " + line for line in operation.splitlines())
                code, report = self.run_fixture(body)
                self.assertEqual(code, 1)
                self.assertTrue(report["successful"])
                self.assertEqual(report["leaks"][kind], 1)

    def test_quiet_mode_keeps_failure_payloads_in_the_log(self):
        code, report = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        print('PRIVATE_CLI_PROBE')
        raise ValueError('PRIVATE_CLI_PROBE')
""", "--quiet")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["console_mode"], "quiet")
        self.assertEqual(self.last_process.stderr, "")
        self.assertIn("ValueError: PRIVATE_CLI_PROBE", self.last_log)

    def test_fixture_failures_include_setup_or_teardown_output(self):
        fixtures = {
            "setUpModule": "def setUpModule():\n    print('FIXTURE_OUTPUT')\n    raise RuntimeError('PRIVATE_CLI_PROBE')\n",
            "tearDownModule": "def tearDownModule():\n    print('FIXTURE_OUTPUT')\n    raise RuntimeError('PRIVATE_CLI_PROBE')\n",
            "setUpClass": "    @classmethod\n    def setUpClass(cls):\n        print('FIXTURE_OUTPUT')\n        raise RuntimeError('PRIVATE_CLI_PROBE')\n",
            "tearDownClass": "    @classmethod\n    def tearDownClass(cls):\n        print('FIXTURE_OUTPUT')\n        raise RuntimeError('PRIVATE_CLI_PROBE')\n",
        }
        for name, fixture in fixtures.items():
            with self.subTest(fixture=name):
                body = "import unittest\n"
                if name.endswith("Module"):
                    body += fixture
                body += "class Fixture(unittest.TestCase):\n"
                if name.endswith("Class"):
                    body += fixture
                body += "    def test_body(self):\n        print('PASS_BODY')\n"
                code, report = self.run_fixture(body)
                self.assertNotEqual(code, 0)
                self.assertFalse(report["passed"])
                for marker in (name, "FIXTURE_OUTPUT", "RuntimeError: PRIVATE_CLI_PROBE"):
                    self.assertIn(marker, self.last_process.stderr)
                self.assertNotIn("PASS_BODY", self.last_process.stderr)

    def test_failed_subtest_retains_its_identity_and_all_parent_output(self):
        code, report = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        with self.subTest(seed=7):
            print('SUBTEST_OUTPUT')
            self.fail('PRIVATE_CLI_PROBE')
        print('AFTER_SUBTEST')
""")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["cases"][0]["status"], "failed")
        for marker in ("seed=7", "SUBTEST_OUTPUT", "AFTER_SUBTEST", "AssertionError: PRIVATE_CLI_PROBE"):
            self.assertIn(marker, self.last_process.stderr)

    def test_async_errors_include_teardown_and_cleanup_diagnostics(self):
        code, report = self.run_fixture("""import unittest, asyncio
class Fixture(unittest.IsolatedAsyncioTestCase):
    async def test_body(self):
        self.addAsyncCleanup(self.cleanup)
        await asyncio.sleep(0)
        print('ASYNC_OUTPUT')
        raise ValueError('PRIVATE_CLI_PROBE')
    async def asyncTearDown(self):
        await asyncio.sleep(0)
        print('ASYNC_TEARDOWN')
    async def cleanup(self):
        await asyncio.sleep(0)
        print('ASYNC_CLEANUP')
        raise RuntimeError('PRIVATE_CLI_PROBE')
""")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["cases"][0]["status"], "error")
        for marker in ("ASYNC_OUTPUT", "ASYNC_TEARDOWN", "ASYNC_CLEANUP",
                       "ValueError: PRIVATE_CLI_PROBE", "RuntimeError: PRIVATE_CLI_PROBE"):
            self.assertIn(marker, self.last_process.stderr)

    def test_nonpassing_outcomes_remain_visible_without_turning_green(self):
        outcomes = (
            ("@unittest.skip('PRIVATE_CLI_PROBE')", "pass", "SKIP", "skipped"),
            ("@unittest.expectedFailure", "self.fail('PRIVATE_CLI_PROBE')", "EXPECTED FAILURE", "expected_failure"),
            ("@unittest.expectedFailure", "pass", "UNEXPECTED SUCCESS", "unexpected_success"),
        )
        for decorator, operation, label, status in outcomes:
            with self.subTest(status=status):
                body = f"import unittest\nclass Fixture(unittest.TestCase):\n    {decorator}\n    def test_body(self):\n        {operation}\n"
                code, report = self.run_fixture(body)
                self.assertNotEqual(code, 0)
                self.assertFalse(report["passed"])
                self.assertEqual(report["cases"][0]["status"], status)
                self.assertIn(label, self.last_process.stderr)

    def test_large_unicode_failure_output_is_streamed_intact(self):
        payload = "a" * 65535 + "\U0001f600\u8bb0\u5fc6"
        code, _ = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    def test_body(self):
        print('a' * 65535 + '\\U0001f600\\u8bb0\\u5fc6')
        self.fail('PRIVATE_CLI_PROBE')
""")
        self.assertNotEqual(code, 0)
        self.assertIn(payload, self.last_process.stderr)
        self.assertNotIn("\ufffd", self.last_process.stderr)

    def test_runner_errors_keep_json_safe_and_show_details_unless_quiet(self):
        body = """import unittest
class BrokenSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        raise RuntimeError('PRIVATE_CLI_PROBE')
def load_tests(loader, tests, pattern):
    return BrokenSuite()
"""
        for arguments in ((), ("--quiet",), ("--all-output",)):
            with self.subTest(arguments=arguments):
                code, report = self.run_fixture(body, *arguments)
                self.assertEqual(code, 2)
                self.assertEqual(report["status"], "runner_error")
                self.assertIn("RuntimeError: PRIVATE_CLI_PROBE", self.last_log)
                if arguments == ("--quiet",):
                    self.assertEqual(self.last_process.stderr, "")
                else:
                    self.assertIn("RuntimeError: PRIVATE_CLI_PROBE", self.last_process.stderr)

    def test_class_fixture_failure_writes_a_failed_report_without_assertion_payload(self):
        code, report = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise RuntimeError('PRIVATE_CLI_PROBE')
    def test_body(self):
        pass
""")
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        self.assertEqual(report["cases"][0]["error_type"], "RuntimeError")

    def test_a_skipped_suite_is_not_accepted_even_when_unittest_reports_success(self):
        code, report = self.run_fixture("""import unittest
class Fixture(unittest.TestCase):
    @unittest.skip('PRIVATE_CLI_PROBE')
    def test_body(self):
        pass
""")
        self.assertNotEqual(code, 0)
        self.assertTrue(report["successful"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["skips"], 1)

    def test_successful_tests_cannot_hide_a_source_edit(self):
        code, report = self.run_fixture("""import unittest
from pathlib import Path
class Fixture(unittest.TestCase):
    def test_body(self):
        Path(__file__).write_text('# changed during acceptance', encoding='utf-8')
""")
        self.assertNotEqual(code, 0)
        self.assertTrue(report["successful"])
        self.assertFalse(report["source_unchanged"])

    def test_successful_tests_cannot_hide_project_root_storage(self):
        code, report = self.run_fixture("""import unittest
from pathlib import Path
class Fixture(unittest.TestCase):
    def test_body(self):
        Path('.att_doc_libs').mkdir()
""")
        self.assertNotEqual(code, 0)
        self.assertTrue(report["successful"])
        self.assertTrue(report["root_doclib_exists"])

    def test_successful_tests_cannot_hide_resource_warnings(self):
        for arguments in ((), ("-v",), ("--quiet",), ("--all-output",)):
            with self.subTest(arguments=arguments):
                code, report = self.run_fixture("""import unittest
import warnings
class Fixture(unittest.TestCase):
    def test_body(self):
        warnings.warn('PRIVATE_CLI_PROBE', ResourceWarning)
""", *arguments)
                self.assertNotEqual(code, 0)
                self.assertTrue(report["successful"])
                self.assertFalse(report["passed"])
                self.assertEqual(report["leaks"]["ResourceWarning:"], 1)
                self.assertIn("ResourceWarning:", self.last_log)
                if arguments == ("--quiet",):
                    self.assertEqual(self.last_process.stderr, "")
                else:
                    self.assertIn("Resource diagnostic", self.last_process.stderr)
