from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Gemma LangChain FastAPI"
    app_env: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    google_api_key: str = Field(default="", repr=False)
    gemma_model: str = "gemma-4-31b-it"
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 4096
    request_timeout_seconds: int = 120

    pexels_api_key: str = Field(default="", repr=False)
    pixabay_api_key: str = Field(default="", repr=False)
    unsplash_access_key: str = Field(default="", repr=False)

    sarvam_api_key: str = Field(default="", repr=False)
    sarvam_lang: str = "en-IN"
    sarvam_pace: float = 1.2
    sarvam_sample_rate: int = 24000
    sarvam_speaker: str = "shubh"
    sarvam_model: str = "bulbul:v3"

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("api_v1_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/") or "/api/v1"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
