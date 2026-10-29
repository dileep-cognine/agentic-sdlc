from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr = SecretStr("postgresql+psycopg://ba:ba_local@localhost:15432/ba")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str = ""
    ollama_model: str = ""
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)
    ollama_temperature: float = Field(default=0, ge=0, le=2)
    ollama_max_attempts: int = Field(default=3, ge=1, le=3)
    ollama_num_predict: int = Field(default=4096, ge=256, le=16000)
    ollama_think: Literal["auto", "off", "low", "medium", "high"] = "auto"
    clarification_batch_size: int = Field(default=5, ge=1, le=5)


@lru_cache
def get_settings() -> Settings:
    return Settings()
