"""Observe real Python diagnostics independently of ordinary test output."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import gc
import importlib.machinery
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
import warnings


KINDS = ("Task exception was never retrieved", "Task was destroyed but it is pending",
         "was never awaited", "ResourceWarning:")
DIRECTORY_ENV = "ATT_ACCEPTANCE_DIAGNOSTICS"
BOOTSTRAP_ENV = "ATT_ACCEPTANCE_DIAGNOSTIC_BOOTSTRAP"
_installed = False
_originals = None
_pid = os.getpid()
_lock = threading.RLock()
_token = uuid.uuid4().hex
_bootstrap_paths = set()
_scope = ContextVar("acceptance_diagnostic_scope", default=None)
_fallback = None


def _record(kind):
    global _pid, _lock
    active = _scope.get() or _fallback
    directory = active[0] if active else None
    if not directory or not Path(directory).is_dir():
        return
    if _pid != os.getpid():
        _pid, _lock = os.getpid(), threading.RLock()
    event = json.dumps({"kind": kind, "pid": _pid}, separators=(",", ":")).encode("ascii") + b"\n"
    with _lock:
        path = Path(directory) / f"{_pid}-{_token}.jsonl"
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if os.write(descriptor, event) != len(event):
                raise OSError("The diagnostic event was not written completely.")
        finally:
            os.close(descriptor)


def _warning_kind(message, category):
    if issubclass(category, ResourceWarning):
        return "ResourceWarning:"
    if issubclass(category, RuntimeWarning) and "was never awaited" in str(message):
        return "was never awaited"
    return None


def install():
    """Install once, including in Python children using the bootstrap module."""
    global _installed, _originals, _fallback
    if _installed:
        return
    showwarning = warnings.showwarning
    exception_handler = asyncio.BaseEventLoop.default_exception_handler
    unraisable = sys.unraisablehook
    popen = subprocess.Popen.__init__
    signature = inspect.signature(popen)

    @wraps(showwarning)
    def observed_warning(message, category, filename, lineno, file=None, line=None):
        kind = _warning_kind(message, category)
        if kind:
            _record(kind)
        return showwarning(message, category, filename, lineno, file=file, line=line)

    @wraps(exception_handler)
    def observed_exception(loop, context):
        message = context.get("message", "")
        future = context.get("task", context.get("future"))
        if isinstance(future, asyncio.Future):
            if message.endswith("exception was never retrieved") and isinstance(context.get("exception"), BaseException):
                _record("Task exception was never retrieved")
            elif message == "Task was destroyed but it is pending!":
                _record("Task was destroyed but it is pending")
        return exception_handler(loop, context)

    @wraps(unraisable)
    def observed_unraisable(event):
        if event.exc_type is not None and issubclass(event.exc_type, Warning):
            kind = _warning_kind(event.exc_value, event.exc_type)
            if kind:
                _record(kind)
        return unraisable(event)

    @wraps(popen)
    def observed_popen(process, *args, **kwargs):
        bound = signature.bind(process, *args, **kwargs)
        supplied = bound.arguments.get("env")
        active = _scope.get() or _fallback
        directory, bootstrap_path = active if active else (None, None)
        if directory and bootstrap_path and (supplied is None or supplied.get(DIRECTORY_ENV) == directory):
            environment = dict(os.environ if supplied is None else supplied)
            environment[DIRECTORY_ENV] = directory
            environment[BOOTSTRAP_ENV] = bootstrap_path
            paths = environment.get("PYTHONPATH", "").split(os.pathsep)
            environment["PYTHONPATH"] = os.pathsep.join([bootstrap_path, *(
                path for path in paths if path and path != bootstrap_path)])
            bound.arguments["env"] = environment
        return popen(*bound.args, **bound.kwargs)

    _originals = showwarning, exception_handler, unraisable, popen
    _fallback = (os.environ.get(DIRECTORY_ENV), os.environ.get(BOOTSTRAP_ENV))
    warnings.showwarning = observed_warning
    asyncio.BaseEventLoop.default_exception_handler = observed_exception
    sys.unraisablehook = observed_unraisable
    subprocess.Popen.__init__ = observed_popen
    _installed = True


def bootstrap(path):
    """Preserve an existing sitecustomize before installing child observers."""
    directory = Path(path).resolve().parent
    _bootstrap_paths.add(directory)
    search = [entry for entry in sys.path if isinstance(entry, str)
              and Path(entry or os.curdir).resolve() not in _bootstrap_paths]
    previous = importlib.machinery.PathFinder.find_spec("sitecustomize", search)
    previous_filters = list(warnings.filters)
    try:
        if previous is not None and previous.loader is not None:
            module = importlib.util.module_from_spec(previous)
            sys.modules["sitecustomize"] = module
            previous.loader.exec_module(module)
    finally:
        install()
        if not sys.warnoptions and warnings.filters == previous_filters:
            warnings.simplefilter("default", ResourceWarning)


def counts(directory):
    if not Path(directory).is_dir():
        raise ValueError("Diagnostic evidence is missing.")
    result = dict.fromkeys(KINDS, 0)
    for path in sorted(Path(directory).glob("*.jsonl")):
        for line in path.read_bytes().splitlines():
            event = json.loads(line)
            if (not isinstance(event, dict) or set(event) != {"kind", "pid"}
                    or event["kind"] not in result or type(event["pid"]) is not int or event["pid"] <= 0):
                raise ValueError("Invalid diagnostic event evidence.")
            result[event["kind"]] += 1
    return result


@contextmanager
def observe_diagnostics(output):
    """Record typed events from this process and context-inheriting children."""
    global _installed, _originals, _fallback
    directory = output / "diagnostics"
    directory.mkdir()
    bootstrap_path = output / "diagnostic-bootstrap"
    bootstrap_path.mkdir()
    module_name = "scripts.acceptance.diagnostics"
    source = str(Path(__file__).resolve())
    (bootstrap_path / "sitecustomize.py").write_text(
        "import importlib.util as _util, sys as _sys\n"
        f"_name = {module_name!r}\n"
        "_module = _sys.modules.get(_name)\n"
        "if _module is None:\n"
        f"    _spec = _util.spec_from_file_location(_name, {source!r})\n"
        "    _module = _util.module_from_spec(_spec)\n"
        "    _sys.modules[_name] = _module\n"
        "    _spec.loader.exec_module(_module)\n"
        "_module.bootstrap(__file__)\n", encoding="utf-8")
    keys = (DIRECTORY_ENV, BOOTSTRAP_ENV, "PYTHONPATH")
    previous = {key: os.environ.get(key) for key in keys}
    already_installed = _installed
    os.environ[DIRECTORY_ENV] = str(directory)
    os.environ[BOOTSTRAP_ENV] = str(bootstrap_path)
    os.environ["PYTHONPATH"] = str(bootstrap_path) + os.pathsep + os.environ.get("PYTHONPATH", "")
    token = _scope.set((str(directory), str(bootstrap_path)))
    try:
        install()
        try:
            yield directory
        finally:
            with warnings.catch_warnings():
                warnings.simplefilter("default", ResourceWarning)
                warnings.simplefilter("default", RuntimeWarning)
                gc.collect()
    finally:
        _scope.reset(token)
        if not already_installed and _originals is not None:
            (warnings.showwarning, asyncio.BaseEventLoop.default_exception_handler,
             sys.unraisablehook, subprocess.Popen.__init__) = _originals
            _installed, _originals, _fallback = False, None, None
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
