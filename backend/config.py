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

    @model_validator(mode="after")
    def require_llm_configuration(self):
        if self.llm_mode == "openai" and (
            not self.openai_api_key.get_secret_value() or not self.openai_model
        ):
            raise ValueError("OPENAI_API_KEY and OPENAI_MODEL are required in openai mode")
        return self
