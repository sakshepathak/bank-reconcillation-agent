"""
Database engine and session factory.

Uses a context-manager session pattern so callers never forget to close.
DATABASE_URL is read from settings — swap to Postgres by changing one env var.
Tables are auto-created on first import (safe: uses CREATE TABLE IF NOT EXISTS).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from config.settings import settings

# echo=False in prod — set to True locally to debug SQL
engine = create_engine(settings.DATABASE_URL, echo=False)


def init_db() -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context-manager session. Always commits on clean exit, rolls back on error.

    `expire_on_commit=False` so ORM objects keep their loaded column values
    after the session closes — needed because the views read attributes
    after the `with get_session()` block exits.

    Usage:
        with get_session() as session:
            session.add(record)
    """
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# NOTE: Do NOT auto-call init_db() here.
# Tables can only be created after all SQLModel model classes have been
# imported (so their metadata is registered). Call init_db() explicitly
# after importing the models — see memory/__init__.py or app/-new-main.py.
