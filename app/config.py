"""Centralized application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # -- App --
    app_env: str = "local"
    log_level: str = "INFO"

    # -- OpenAI --
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    # -- Meta WhatsApp Cloud API --
    meta_whatsapp_token: str = ""
    meta_verify_token: str = ""
    meta_phone_number_id: str = ""
    meta_app_secret: str = ""
    meta_graph_api_version: str = "v20.0"

    # -- Qdrant --
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "product_embeddings_v1"

    # -- Tavily --
    tavily_api_key: str = ""

    # -- Database --
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/corporate_gifting"

    # -- Redis (optional) --
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    # -- Website / storefront auth (JWT) --
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 1 day

    # -- Orders / checkout --
    payment_webhook_secret: str = ""
    gst_rate: float = 0.18  # 18% GST applied to order subtotals
    default_warehouse_id: int | None = None  # None -> pick first warehouse with stock

    # -- Search tuning --
    search_min_catalog_results: int = 3
    search_min_similarity: float = 0.72
    search_budget_band_low: float = 0.6
    search_budget_band_high: float = 1.15
    search_top_k_semantic: int = 20
    search_top_k_sql: int = 50

    # -- Embeddings job --
    embeddings_schedule_enabled: bool = False
    embeddings_batch_size: int = 100

    # -- LangSmith / tracing (optional) --
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""

    @property
    def whatsapp_api_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.meta_graph_api_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
