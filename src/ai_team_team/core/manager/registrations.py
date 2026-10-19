"""Off-registry identity reservations for receipt-bound membership publication."""

import os
import shutil
from dataclasses import dataclass


@dataclass
class AgentRegistration:
    registry: object
    agent: object
    managed_root: str
    generation: int
    library: object = None
    directory: str | None = None
    published: bool = False

    @property
    def library_id(self):
        return f"PDL-{self.agent.agent_id}"

    def prepare(self):
        """Provision an empty, exclusively owned directory without publishing it."""
        if self.library is not None:
            return
        if os.path.islink(self.managed_root):
            raise PermissionError("The managed DocLib root cannot be a symlink.")
        os.makedirs(self.managed_root, exist_ok=True)
        path = os.path.join(self.managed_root, self.library_id)
        os.mkdir(path)
        self.directory = path
        self.library = self.registry.manager._build_document_library(
            lib_id=self.library_id, name=f"{self.agent.name} Private Library",
            owner_agent_id=self.agent.agent_id, library_kind="agent_private",
            description=f"Persistent private workspace for agent {self.agent.name}.",
            is_public_visible=False, storage_dir=path,
        )

    def release(self):
        """Release only this reservation and its unaccepted empty workspace."""
        manager = self.registry.manager
        if not self.published and self.directory is not None:
            shutil.rmtree(self.directory)
            self.directory = None
        # Local cleanup has no authority to publish resources. Do not retain
        # the resource gate while an unrelated topology reader is still active.
        with manager._topology_lock:
            if self.registry.pending.get(self.agent.agent_id) is self:
                self.registry.pending.pop(self.agent.agent_id)
                self.registry.refresh_names()

    def publish(self):
        """Caller owns resource, topology, and snapshot publication locks."""
        registry, agent = self.registry, self.agent
        manager = registry.manager
        manager.libraries[self.library_id] = self.library
        manager._library_files[self.library_id] = {}
        manager._resources.bind(self.library)
        agent._private_doc_library_id = self.library_id
        agent._manager = manager
        registry.by_id[agent.agent_id] = agent
        registry.active_by_name[agent.name] = agent
        self.published = True
        registry.pending.pop(agent.agent_id, None)
        registry.refresh_names()
