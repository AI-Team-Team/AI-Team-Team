"""Composed persisted state validator."""

from typing import TYPE_CHECKING

from .links import LinkNormalizationMixin
from .validator import SnapshotValidationMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class StateValidator(SnapshotValidationMixin, LinkNormalizationMixin):
    """Validates configuration, identities, topology, and DocLib state."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
