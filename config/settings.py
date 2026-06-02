"""
Application settings — loaded from .env via pydantic-settings.

All configuration lives here. No magic strings anywhere else in the codebase.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM providers ────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "groq"
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY: Optional[str] = None

    # Gemini — primary for vision/extraction (native PDF, structured output)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_API_KEY_BACKUP_1: Optional[str] = None
    GEMINI_API_KEY_BACKUP_2: Optional[str] = None
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"
    GEMINI_TEXT_MODEL: str = "gemini-2.5-flash"

    # OpenRouter — automatic fallback when Gemini errors / rate-limits
    OPENROUTER_API_KEY: Optional[str] = None
    # MUST support vision — used as fallback for invoice/bank PDF extraction.
    OPENROUTER_FALLBACK_MODEL: str = "openai/gpt-4o-mini"

    # Groq fallback models
    AGENT_MODEL: str = "llama-3.3-70b-versatile"
    CONTEXT_MODEL: str = "llama-3.1-8b-instant"
    # Legacy Groq vision model — kept only as last-resort fallback for vision tasks
    VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # ── Invoice extraction ────────────────────────────────────────────────────
    UPLOAD_DIR: str = "data/uploads"
    MAX_INVOICES_PER_CATEGORY: int = 10   # per-uploader (sales OR purchase)
    MAX_INVOICES_PER_RUN: int = 20        # combined ceiling (sales + purchase)
    EXTRACT_PARALLELISM: int = 2          # Gemini free tier is 5 req/min per key — be gentle

    # ── Qdrant vector store ───────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "bank_recon_kb"

    # ── Embedding models (local, via fastembed — no API key needed) ───────────
    DENSE_MODEL: str = "BAAI/bge-small-en-v1.5"   # 384-dim cosine
    SPARSE_MODEL: str = "Qdrant/bm25"              # BM25 keyword

    # ── Retrieval tuning ──────────────────────────────────────────────────────
    HYBRID_TOP_K: int = 20   # candidates pulled from each sub-search
    RERANK_TOP_K: int = 5    # final results returned after RRF fusion

    # ── Matching engine ───────────────────────────────────────────────────────
    # Amount tolerance for fuzzy amount matching (absolute value difference)
    AMOUNT_TOLERANCE: float = 0.05
    # Date window (days) for fuzzy date matching
    DATE_WINDOW_DAYS: int = 3
    # Minimum fuzzy string similarity score (0-100)
    FUZZY_SCORE_THRESHOLD: int = 70

    # ── Auth ─────────────────────────────────────────────────────────────────
    # True = anyone can register a new account. Default on so you can always
    # add users/businesses. Set to false in .env to lock down a production box.
    ALLOW_REGISTRATION: bool = True

    # ── Persistence (SQLite for local dev; swap URL for Postgres in prod) ─────
    DATABASE_URL: str = "sqlite:///./bank_recon.db"

    # ── Observability (optional LangSmith) ───────────────────────────────────
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROJECT: str = "bank-reconciliation-agent"


settings = Settings()
