"""Operation-local formation candidates and receipt-owned publication."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar


REGISTRIES = ("requests", "invitations", "revisions", "decisions", "drafts")


class FormationCandidate:
    """Clone only locked proposal entities, then publish per-entity differences."""

    def __init__(self, service):
        self.service = service
        self.owner = asyncio.current_task()
        self.base = {name: dict(rows) for name, rows in service._published.items()}
        self.state = {name: dict(rows) for name, rows in self.base.items()}
        self.cloned = {name: set() for name in REGISTRIES}
        self.dirty = service.manager._new_dirty_state(provisional=True)

    def clone(self, name, key):
        if key in self.cloned[name] and (
                self.state[name].get(key) != self.base[name].get(key)
                or self.service._published[name].get(key) == self.base[name].get(key)):
            return
        published = self.service._published[name]
        if key in published:
            self.base[name][key] = published[key]
            self.state[name][key] = published[key].model_copy(deep=True)
        self.cloned[name].add(key)

    def scope_request(self, request_id):
        self.clone("requests", request_id)
        for name in ("invitations", "drafts", "revisions", "decisions"):
            published = self.service._published[name]
            keys = {key for rows in (self.base[name], self.state[name], published)
                for key, row in rows.items() if row.request_id == request_id}
            for key in keys:
                if self.state[name].get(key) != self.base[name].get(key):
                    continue
                if key not in published:
                    self.base[name].pop(key, None)
                    self.state[name].pop(key, None)
                elif name in {"invitations", "drafts"}:
                    self.clone(name, key)
                else:
                    # Immutable history can advance while a draft waits for
                    # its proposal lock; refresh references without copying it.
                    self.base[name][key] = self.state[name][key] = published[key]


class FormationPublication:
    """An immutable, conflict-checked patch; unrelated proposals survive it."""

    def __init__(self, service, candidate, dirty):
        self.service = service
        self.candidate = candidate
        self.created_teams = tuple(service.manager.teams[team_id]
            for team_id in dirty.get("_creation_teams", ()))
        self.patch = {}
        self.expected = {}
        for name in REGISTRIES:
            selector = dirty[f"formation_{name}"]
            keys = set(candidate.base[name]) | set(candidate.state[name])
            selected = lambda key: (key in selector if name in {"requests", "drafts"}
                else key[0] in selector if name == "invitations"
                else (candidate.state[name].get(key) or candidate.base[name][key]).request_id in selector)
            changed = {key for key in keys if selected(key)
                and candidate.state[name].get(key) != candidate.base[name].get(key)}
            self.patch[name] = {key: candidate.state[name][key].model_copy(deep=True)
                if key in candidate.state[name] else None for key in changed}
            self.expected[name] = {key: candidate.base[name].get(key) for key in changed}

    def validate(self):
        for name in REGISTRIES:
            for key, expected in self.expected[name].items():
                if self.service._published[name].get(key) != expected:
                    raise ValueError("The accepted formation changed before this candidate could commit.")

    def projection(self):
        result = {name: dict(rows) for name, rows in self.service._published.items()}
        for name, patch in self.patch.items():
            for key, row in patch.items():
                if row is None:
                    result[name].pop(key, None)
                else:
                    result[name][key] = row
        return result

    def publish(self):
        with self.service._state_lock:
            for name, patch in self.patch.items():
                for key, row in patch.items():
                    if row is None:
                        self.service._published[name].pop(key, None)
                        self.candidate.base[name].pop(key, None)
                    else:
                        self.service._published[name][key] = row
                        self.candidate.base[name][key] = row
            # The accepted proposal and its ordinary visibility switch share
            # the same snapshot critical section, before observers can save.
            for team in self.created_teams:
                team._publication_pending = False
                team._creation_publication = None


class FormationPublicationMixin:
    def _initialize_publication(self):
        self._published = {name: {} for name in REGISTRIES}
        self._candidate = ContextVar(f"att-formation-candidate-{id(self)}", default=None)

    def current_candidate(self):
        candidate = self._candidate.get()
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        # Detached framework tasks must acquire their own operation and locks.
        return candidate if candidate is not None and candidate.owner is task else None

    def registry(self, name):
        candidate = self.current_candidate()
        return candidate.state[name] if candidate is not None else self._published[name]

    @property
    def requests(self):
        return self.registry("requests")

    @property
    def invitations(self):
        return self.registry("invitations")

    @property
    def revisions(self):
        return self.registry("revisions")

    @property
    def decisions(self):
        return self.registry("decisions")

    @property
    def drafts(self):
        return self.registry("drafts")

    @asynccontextmanager
    async def stage(self, *, request_id=None, draft_id=None):
        candidate = self.current_candidate()
        root = candidate is None
        if root:
            with self._state_lock:
                candidate = FormationCandidate(self)
            token = self._candidate.set(candidate)
            batch_token = self.manager._persistence_batch.set(candidate.dirty)
        try:
            with self._state_lock:
                if request_id is not None:
                    candidate.scope_request(request_id)
                if draft_id is not None:
                    candidate.clone("drafts", draft_id)
            yield candidate
        finally:
            if root:
                # Accepted mail has its exact notice in the record index.
                # Withdraw only this operation's still-unaccepted additions.
                self.manager._inbox.finish_provisional(candidate.dirty, accepted=False)
                self.manager._persistence_batch.reset(batch_token)
                self._candidate.reset(token)

    def commit_dirty(self, dirty):
        candidate = self.current_candidate()
        if candidate is None:
            return dirty
        merged = self.manager._new_dirty_state(provisional=True)
        self.manager._merge_dirty_state(merged, candidate.dirty)
        self.manager._merge_dirty_state(merged, dirty)
        # Preserve domain-specific commit overrides, not just dirty selectors.
        for key, value in dirty.items():
            if key not in merged:
                merged[key] = value
        return merged

    def prepare_publication(self, dirty):
        candidate = self.current_candidate()
        if candidate is None or dirty is None or not any(dirty[f"formation_{name}"] for name in REGISTRIES):
            return None
        return FormationPublication(self, candidate, dirty)
