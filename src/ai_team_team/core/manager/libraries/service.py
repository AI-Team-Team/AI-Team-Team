"""Composed manager-owned DocLib service."""

from typing import TYPE_CHECKING

from .access import LibraryAccessMixin
from .factory import LibraryFactoryMixin
from .model_reads import ModelReadMixin
from .private_files import PrivateFileMixin
from .team_files import TeamFileMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class LibraryService(
    LibraryAccessMixin,
    ModelReadMixin,
    TeamFileMixin,
    PrivateFileMixin,
    LibraryFactoryMixin,
):
    """Owns ACL-aware team and private DocLib runtime operations."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
