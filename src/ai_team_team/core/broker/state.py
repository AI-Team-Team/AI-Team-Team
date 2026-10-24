"""Invocation-local communication candidates published only after a receipt."""

import contextvars
from contextlib import contextmanager


REGISTRIES = (
    "communication_requests", "communication_approvals", "ballots", "agreements", "peer_messages"
)


class BrokerStateMixin:
    def initialize_state(self):
        self._published_state = {name: {} for name in REGISTRIES}
        self._candidate_state = contextvars.ContextVar(f"att-broker-candidate-{id(self)}", default=None)

    @contextmanager
    def stage(self):
        if self._candidate_state.get() is not None:
            raise RuntimeError("Communication state transactions cannot be nested.")
        candidate = {name: dict(values) for name, values in self._published_state.items()}
        token = self._candidate_state.set(candidate)
        try:
            yield candidate
        finally:
            self._candidate_state.reset(token)

    def publish_state(self, candidate):
        self._published_state = candidate

    def registry(self, name):
        candidate = self._candidate_state.get()
        return (candidate if candidate is not None else self._published_state)[name]

    def replace_registry(self, name, values):
        candidate = self._candidate_state.get()
        (candidate if candidate is not None else self._published_state)[name] = values


def _registry_property(name):
    return property(lambda self: self.registry(name), lambda self, values: self.replace_registry(name, values))


for _name in REGISTRIES:
    setattr(BrokerStateMixin, _name, _registry_property(_name))
