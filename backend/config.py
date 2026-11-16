from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"), extra="ignore"
    )
    llm_mode: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = ""
    llm_timeout_seconds: float = Field(default=30, gt=0, le=60)
    validation_agent_url: str = "http://127.0.0.1:8001"
    a2a_timeout_seconds: float = Field(default=45, gt=0, le=70)
    research_timeout_seconds: float = Field(default=90, gt=0, le=100)
    sqlite_path: Path = Path(__file__).parent / "data" / "aurum.sqlite3"
    chroma_path: Path = Path(__file__).parent / "data" / "chroma"
    memory_embedding_adapter: Literal["sentence_transformers", "fake"] = "sentence_transformers"
    memory_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    memory_top_k: int = Field(default=5, ge=1, le=50)
    memory_similarity_threshold: float = Field(default=0.45, ge=-1, le=1)
    memory_cache_similarity_threshold: float = Field(default=0.92, ge=-1, le=1)
    memory_cache_max_entries: int = Field(default=128, ge=1, le=10000)
    memory_max_context_chars: int = Field(default=6000, ge=200, le=30000)
    memory_recent_messages: int = Field(default=4, ge=0, le=20)
    memory_working_max_sessions: int = Field(default=128, ge=1, le=10000)
    memory_working_max_messages: int = Field(default=20, ge=2, le=100)
    memory_working_max_chars: int = Field(default=12000, ge=500, le=100000)
    gold_stale_after_seconds: int = Field(default=7200, ge=1)
    gold_http_timeout_seconds: float = Field(default=10, gt=0, le=30)
    gold_http_attempts: int = Field(default=3, ge=1, le=3)
    internal_job_token: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def require_llm_configuration(self):
        if self.llm_mode == "openai" and (
            not self.openai_api_key.get_secret_value() or not self.openai_model
        ):
            raise ValueError("OPENAI_API_KEY and OPENAI_MODEL are required in openai mode")
        return self
