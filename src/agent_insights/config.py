from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./agent-insights.db"
    generation_provider: str = "ollama"
    generation_url: str = "http://127.0.0.1:11434"
    generation_model: str = "gemma3:4b"
    generation_api_key: SecretStr = SecretStr("")
    embedding_provider: str = "ollama"
    embedding_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "embeddinggemma"
    embedding_api_key: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    timeout_seconds: float = Field(180, gt=0)
    lease_seconds: int = Field(900, ge=30)
    max_attempts: int = Field(3, ge=1, le=10)
    max_topics_per_bot: int = Field(128, ge=1, le=10000)
    assignment_similarity: float = Field(0.70, ge=0, le=1)
    assignment_margin: float = Field(0.03, ge=0, le=1)
    discovery_similarity: float = Field(0.80, ge=0, le=1)
    min_sessions_per_topic: int = Field(3, ge=2)
    pending_batch_size: int = Field(100, ge=2, le=200)
    pending_max_days: int = Field(7, ge=1)
    pending_max_reviews: int = Field(3, ge=1)
    clusterer: str = "complete_link"
    umap_dimensions: int = Field(10, ge=2)
    max_facets_per_session: int = Field(5, ge=1, le=20)
    host: str = "127.0.0.1"
    port: int = Field(8766, ge=1, le=65535)

    @model_validator(mode="after")
    def providers_known(self):
        for value in (self.generation_provider, self.embedding_provider):
            if value not in {"ollama", "openai", "demo"}:
                raise ValueError("Provider must be ollama, openai (including vLLM), or demo")
        if self.clusterer not in {"complete_link", "umap_hdbscan"}:
            raise ValueError("Unknown clusterer")
        if self.lease_seconds <= self.timeout_seconds:
            raise ValueError("lease_seconds must exceed timeout_seconds")
        return self
