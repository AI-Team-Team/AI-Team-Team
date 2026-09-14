from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ManagerConfigModel(Base):
    __tablename__ = "manager_config"
    config_key: Mapped[str] = mapped_column(String, primary_key=True)
    config_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)

