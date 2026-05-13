"""
Settings for the application.
"""
from pydantic import BaseModel
from typing import Optional
import os

class Settings(BaseModel):
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./test.db")
    langsmith_api_key: Optional[str] = os.getenv("LANGSMITH_API_KEY", None)

settings = Settings()
