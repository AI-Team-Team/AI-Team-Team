"""Composed atomic state restore service."""

from typing import TYPE_CHECKING

from .hydration import RestoreHydrationMixin
from .publication import RestorePublicationMixin
from .transaction import RestoreTransactionMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class RestoreService(RestoreHydrationMixin, RestoreTransactionMixin, RestorePublicationMixin):
    """Owns staging and atomic publication of restored runtime state."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
