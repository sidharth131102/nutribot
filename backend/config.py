from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NutriBot"
    database_url: str = "sqlite+aiosqlite:///./nutribot.db"
    openai_api_key: str | None = None
    model_name: str = "gpt-4o-mini"
    vector_store_path: str = "rag/faiss_index"
    rag_source_dir: str = "rag/source_docs"
    food_db_path: str = "data/food_db.json"
    max_generation_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_prefix="NUTRIBOT_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
