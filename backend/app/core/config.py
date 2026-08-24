from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "PriceRadar"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    upload_dir: Path = Path("storage/uploads")
    max_upload_mb: int = 25

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("upload_dir", mode="after")
    @classmethod
    def resolve_upload_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_DIR / value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
