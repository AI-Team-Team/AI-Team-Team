"""Reentrant physical path exclusion, including directory/descendant conflicts."""

import threading
from contextlib import contextmanager


class PathLocks:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.active = []

    @staticmethod
    def conflicts(left, right):
        path_a, tree_a = left
        path_b, tree_b = right
        return (path_a == path_b or tree_a and (not path_a or path_b.startswith(path_a + "/"))
                or tree_b and (not path_b or path_a.startswith(path_b + "/")))

    @contextmanager
    def hold(self, paths):
        paths = tuple(sorted(set(paths)))
        owner = threading.get_ident()
        token = owner, paths
        with self.condition:
            self.condition.wait_for(lambda: not any(
                other != owner and any(self.conflicts(a, b) for a in paths for b in held)
                for other, held in self.active))
            self.active.append(token)
        try:
            yield
        finally:
            with self.condition:
                self.active.remove(token)
                self.condition.notify_all()
