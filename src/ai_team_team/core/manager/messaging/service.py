"""One common implementation for chat sources, relationship views, and controls."""

from .base import ChatBase
from .archive import ArchiveMixin
from .membership import MembershipMixin
from .reads import ReadMixin
from .read_receipts import ReadReceiptMixin
from .relationships import RelationshipMixin
from .reminders import ReminderMixin
from .views import ViewMixin
from .writes import WriteMixin


class MessagingService(ArchiveMixin, MembershipMixin, ReadMixin, ReadReceiptMixin, RelationshipMixin, ReminderMixin, ViewMixin, WriteMixin, ChatBase):
    """Only committed source values enter personal activity or public query results."""
