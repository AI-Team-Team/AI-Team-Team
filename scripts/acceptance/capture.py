"""Capture Python, native, and inherited subprocess output in one raw log."""

import contextlib
import ctypes
from functools import lru_cache
import os
import sys


@lru_cache(maxsize=1)
def _c_flushers():
    functions = []
    for library in ("ucrtbase", "msvcrt") if os.name == "nt" else (None,):
        try:
            flush = ctypes.CDLL(library).fflush
        except (OSError, AttributeError):
            continue
        flush.argtypes = [ctypes.c_void_p]
        flush.restype = ctypes.c_int
        functions.append(flush)
    return tuple(functions)


def flush_output():
    """Flush C stdio before taking a byte position or restoring descriptors."""
    for flush in _c_flushers():
        flush(None)
    for stream in (sys.stdout, sys.stderr):
        stream.flush()


def _windows_standard_handles():
    if os.name != "nt":
        return
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    set_handle = kernel.SetStdHandle
    set_handle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
    set_handle.restype = wintypes.BOOL
    for identifier, descriptor in ((-11, 1), (-12, 2)):
        if not set_handle(identifier, msvcrt.get_osfhandle(descriptor)):
            raise ctypes.WinError(ctypes.get_last_error())


@contextlib.contextmanager
def preserved_stderr():
    """Keep a console destination that does not follow redirected fd 2."""
    encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
    with os.fdopen(os.dup(2), "w", encoding=encoding, errors="backslashreplace",
                   buffering=1, newline="") as stream:
        yield stream


@contextlib.contextmanager
def capture_output(log_stream):
    """Restore both OS descriptors even if setup or test execution fails."""
    flush_output()
    with contextlib.ExitStack() as restore:
        restore.callback(_windows_standard_handles)
        for descriptor in (1, 2):
            original = os.dup(descriptor)
            restore.callback(os.close, original)
            restore.callback(os.dup2, original, descriptor)
        for descriptor in (1, 2):
            os.dup2(log_stream.fileno(), descriptor)
        _windows_standard_handles()
        with contextlib.redirect_stdout(log_stream), contextlib.redirect_stderr(log_stream):
            try:
                yield
            finally:
                flush_output()
