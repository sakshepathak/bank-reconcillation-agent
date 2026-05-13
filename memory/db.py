"""
Database connection and session management.
"""
from sqlmodel import create_engine, Session

# Placeholder for DB URL (PostgreSQL with pgvector)
# For local dev, we might use SQLite or local Postgres
DATABASE_URL = "sqlite:///./test.db" # Mock for now

engine = create_engine(DATABASE_URL)

def get_session():
    with Session(engine) as session:
        yield session
