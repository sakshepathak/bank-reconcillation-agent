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

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from config.settings import settings

# echo=False in prod — set to True locally to debug SQL
engine = create_engine(settings.DATABASE_URL, echo=False)


def _run_migrations() -> None:
    """Add columns that SQLModel.metadata.create_all won't add to existing tables."""
    statements = [
        # CompanyProfile: was a shared single row; now one row per org
        "ALTER TABLE company_profile ADD COLUMN org_id INTEGER REFERENCES organization(id)",
        "CREATE INDEX IF NOT EXISTS ix_company_profile_org_id ON company_profile(org_id)",
        # UserProfile: was a shared single row; now one row per user
        "ALTER TABLE user_profile ADD COLUMN user_id INTEGER REFERENCES \"user\"(id)",
        "CREATE INDEX IF NOT EXISTS ix_user_profile_user_id ON user_profile(user_id)",
        # StatementLine: bulk-match columns (1 bank line → N invoices/bills)
        "ALTER TABLE statement_line ADD COLUMN matched_invoice_ids TEXT",
        "ALTER TABLE statement_line ADD COLUMN matched_bill_ids TEXT",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column/index already exists — safe to skip


def init_db() -> None:
    """Create all tables then apply incremental column migrations."""
    SQLModel.metadata.create_all(engine)
    _run_migrations()


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
