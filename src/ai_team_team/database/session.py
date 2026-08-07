from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from ai_team_team.database.persistence import DatabaseStore, WriterLease


@contextmanager
def get_session(db_path: str) -> Generator[Session, None, None]:
    """Yields a strict standalone writer session under an exclusive lease."""
    lease = WriterLease(db_path)
    store = None
    session = None
    try:
        store = DatabaseStore(db_path)
        session = store.session_factory()
        yield session
        session.commit()
    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()
        if store is not None:
            store.close()
        lease.close()
