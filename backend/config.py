from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str = "NutriBot"
    environment: Literal["development", "staging", "production"] = "development"
    frontend_url: str = "http://localhost:3000"

    # LLM
    llm_provider: str = "groq"
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"       # used by meal plan agent
    llm_model_fast: str = "openai/gpt-oss-20b"   # used by intent agent

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "nutribot"

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Email (SendGrid)
    sendgrid_api_key: str = ""
    email_from: str = "noreply@nutribot.ai"
    email_from_name: str = "NutriBot"

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "nutribot-knowledge"

    # RAG
    pdf_source_dir: str = "data"  # PDFs live directly in data/
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_top_k: int = 6

    # Food DB
    food_db_path: str = "data/food_db.json"

    # Chat memory window
    chat_memory_window: int = 6

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
