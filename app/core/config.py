import json
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

    # Cloudflare Workers AI — used to generate the optional AI intro title image.
    # Free-tier text-to-image (Gemini/Imagen currently has no free image quota).
    cloudflare_account_id: str = Field(default="", repr=False)
    cloudflare_api_token: str = Field(default="", repr=False)
    cloudflare_image_model: str = "@cf/black-forest-labs/flux-1-schnell"

    sarvam_api_key: str = Field(default="", repr=False)
    sarvam_lang: str = "en-IN"
    sarvam_pace: float = 1.2
    sarvam_sample_rate: int = 24000
    sarvam_speaker: str = "shubh"
    sarvam_model: str = "bulbul:v3"

    # Video render tuning. Lower these on memory-constrained hosts (e.g. a 1 GB
    # Railway instance) to avoid out-of-memory crashes during MoviePy rendering.
    # video_max_long_edge caps the longer output dimension: 1920 = full 1080p,
    # 1280 = 720p (~half the frame memory), 960 = 540p. render_threads controls
    # how many frames ffmpeg buffers concurrently.
    video_max_long_edge: int = 1920
    render_threads: int = 4
    # Render engine: "ffmpeg" (fast — native ffmpeg assembly + ASS captions) or
    # "moviepy" (legacy fallback). ffmpeg is much faster and lower-memory.
    render_engine: str = "ffmpeg"

    # Output quality tuning. Higher quality = larger files + slower/heavier
    # encodes. Lower these back toward "ultrafast"/23 on memory- or CPU-limited
    # hosts if renders time out or OOM.
    #   render_preset : x264 speed/compression trade-off. Slower = better quality
    #                   per byte. One of: ultrafast, superfast, veryfast, faster,
    #                   fast, medium, slow, slower, veryslow.
    #   render_crf    : constant quality, 0 (lossless) .. 51 (worst). Lower =
    #                   better looking + bigger. 18 ≈ visually lossless, 23 =
    #                   x264 default, 28 = small/low.
    #   render_fps    : output frames per second. 30 = smooth, 24 = cinematic/
    #                   lighter, 60 = very smooth but ~2x the frames to encode.
    #   render_audio_bitrate : AAC audio bitrate, e.g. 128k, 160k, 192k, 256k.
    render_preset: str = "medium"
    render_crf: int = 18
    render_fps: int = 30
    render_audio_bitrate: str = "192k"

    # Personal Google Drive OAuth configuration. Create an OAuth "Desktop/Web"
    # client in Google Cloud and register this callback URL there.
    gdrive_client_id: str = Field(default="", repr=False)
    gdrive_client_secret: str = Field(default="", repr=False)
    gdrive_redirect_uri: str = "http://localhost:8000/api/v1/login/google/callback"

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
        # Accept either a JSON array (e.g. '["http://a","http://b"]') or a plain
        # comma-separated string. pydantic-settings JSON-decodes list env vars
        # first, so this usually receives a list already — handle the string
        # forms defensively so both .env styles work.
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed]
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
