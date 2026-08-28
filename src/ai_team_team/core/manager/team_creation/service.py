"""Composed atomic AgentTeam creation service."""

from typing import TYPE_CHECKING

from .staging import TeamCreationStagingMixin
from .transaction import TeamCreationTransactionMixin
from .validation import TeamCreationValidationMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class TeamCreationService(
    TeamCreationTransactionMixin,
    TeamCreationValidationMixin,
    TeamCreationStagingMixin,
):
    """Owns validation, staging, commit, and rollback for new AgentTeams."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
