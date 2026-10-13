"""Schema 12 record tables, selected explicitly by trusted common services."""

from ..base import Base
from . import chat, evidence, execution, personal

ACTIVITY_TABLES = {
    name: item for name, item in Base.metadata.tables.items()
    if item.info.get("activity_record")
}

__all__ = ["ACTIVITY_TABLES", "chat", "evidence", "execution", "personal"]
