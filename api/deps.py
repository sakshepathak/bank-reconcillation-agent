"""FastAPI dependency: yields a DB session per request."""
from typing import Generator
from sqlmodel import Session
from memory.db import engine


def get_db() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
