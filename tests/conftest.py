"""
Shared pytest fixtures.

Each test function gets its own fresh in-memory SQLite database via
FastAPI's dependency override mechanism. The production engine in
memory.db is never touched by tests.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Importing models registers them on SQLModel.metadata so create_all picks them up.
import memory.models  # noqa: F401
from api.deps import get_db
from api.main import app


@pytest.fixture(scope="function")
def test_engine():
    """A fresh in-memory SQLite per test. StaticPool keeps the same connection
    across the test so the in-memory DB persists for its lifetime."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def client(test_engine):
    """TestClient with get_db overridden to use the test engine."""

    def _override_get_db():
        with Session(test_engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
