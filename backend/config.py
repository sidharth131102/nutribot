from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str = "NutriBot"
    environment: Literal["development", "staging", "production"] = "development"
    frontend_url: str = "http://localhost:3000"

    # LLM
    llm_provider: str = "groq"  # "groq" | "azure_openai" | "azure_openai_challenger" -- Groq kept configured as a fallback option
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"       # used by meal plan agent
    llm_model_fast: str = "openai/gpt-oss-20b"   # used by intent agent

    # LLM (Azure OpenAI)
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment_full: str = "gpt-5-mini"
    azure_openai_deployment_fast: str = "gpt-5-mini"  # same deployment as full by default -- see docs/CURRENT_STATE.md
    # True = reasoning model (gpt-5 family): pass reasoning_effort, never temperature.
    # False = classic chat model (gpt-4.1): pass temperature, never reasoning_effort.
    # Promoting a classic model to primary = point the deployments at it + flip this to False.
    azure_openai_reasoning_model: bool = True

    # Azure OpenAI challenger (Phase 7) -- a second deployment on the SAME
    # resource (endpoint/key/version shared), eval-only until promoted.
    # Empty deployment name = challenger not configured.
    azure_openai_challenger_deployment_full: str = ""
    azure_openai_challenger_deployment_fast: str = ""
    azure_openai_challenger_reasoning_model: bool = False

    # Eval (Phase 6/7) -- the factory entry the DeepEval judge is pinned to.
    # Deliberately NOT llm_provider: in `--compare` mode the challenger arm
    # would otherwise judge its own output.
    eval_judge_provider: str = "azure_openai"

    # Azure Blob Storage (Phase 4: medical document uploads)
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "medical-documents"

    # Azure Document Intelligence (Phase 4: medical document OCR)
    azure_doc_intelligence_endpoint: str = ""
    azure_doc_intelligence_api_key: str = ""

    # Azure Speech (STT) + Translator -- multilingual voice input.
    # One "Azure AI services" multi-service resource covers both with a
    # single key/region; leave the translator fields empty to reuse the
    # speech key/region. Empty speech key = voice input disabled (the token
    # endpoint returns 503, the mic button hides). Empty translator key AND
    # empty speech key = every message is treated as English, no translation.
    azure_speech_key: str = ""
    azure_speech_region: str = ""              # e.g. "centralindia", "eastus"
    azure_translator_key: str = ""
    azure_translator_region: str = ""
    azure_translator_endpoint: str = "https://api.cognitive.microsofttranslator.com"
    # Candidate spoken languages for auto-detection (BCP-47, comma-separated).
    # At-start language identification supports at most 4; one locale per
    # language (en-IN and en-US together is rejected by the service).
    speech_recognition_languages: str = "en-IN,hi-IN,ml-IN,fr-FR"
    # Master switch for translate-at-the-edges. Off = pipeline sees the raw
    # message and replies in English regardless of the user's language.
    multilingual_enabled: bool = True

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

    # RAG hybrid search + reranking (Phase 5)
    rag_corpus_path: str = "data/rag_corpus.json"
    rag_fusion_pool_size: int = 20

    # Food DB
    food_db_path: str = "data/food_db.json"

    # Chat memory window -- 6 was tuned to stay under Groq's 8000 TPM ceiling;
    # Azure OpenAI's real quota (100K+ TPM) has room for more history.
    chat_memory_window: int = 10

    # LangSmith tracing (Phase 6) -- opt-in, off by default since it requires
    # an external account/API key
    langsmith_api_key: str = ""
    langsmith_project: str = "nutribot"
    langsmith_tracing_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
