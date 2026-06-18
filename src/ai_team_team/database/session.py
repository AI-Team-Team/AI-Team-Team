from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
from ai_team_team.database.models import Base

def get_engine(db_path: str):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False}
    )

@contextmanager
def get_session(db_path: str, disable_fks: bool = False) -> Generator[Session, None, None]:
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    if disable_fks:
        session.execute(text("PRAGMA foreign_keys = OFF;"))
        
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
