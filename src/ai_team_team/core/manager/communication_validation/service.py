"""Composed communication state validator."""

from typing import TYPE_CHECKING

from .validator import CommunicationValidationMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class CommunicationStateValidator(CommunicationValidationMixin):
    """Validates persisted communication governance and delivery records."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
