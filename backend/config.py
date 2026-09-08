from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str = "NutriBot"
    environment: Literal["development", "staging", "production"] = "development"
    frontend_url: str = "http://localhost:3000"

    # LLM
    llm_provider: str = "groq"  # "groq" | "azure_openai" -- Groq kept configured as a fallback option
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"       # used by meal plan agent
    llm_model_fast: str = "openai/gpt-oss-20b"   # used by intent agent

    # LLM (Azure OpenAI)
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment_full: str = "gpt-5-mini"
    azure_openai_deployment_fast: str = "gpt-5-mini"  # same deployment as full by default -- see docs/CURRENT_STATE.md

    # Azure Blob Storage (Phase 4: medical document uploads)
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "medical-documents"

    # Azure Document Intelligence (Phase 4: medical document OCR)
    azure_doc_intelligence_endpoint: str = ""
    azure_doc_intelligence_api_key: str = ""

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

    # Chat memory window -- 6 was tuned to stay under Groq's 8000 TPM ceiling;
    # Azure OpenAI's real quota (100K+ TPM) has room for more history.
    chat_memory_window: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
