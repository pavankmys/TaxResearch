"""Worker settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Worker configuration from environment variables."""

    # Database URL (required, no default)
    database_url: str

    # Object store configuration
    object_store: str = "local"  # "s3" or "local"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    local_store_path: str = "./data"

    # Watch folder for file uploads (POC only). Container path is /watch.
    watch_folder: str = "./watch"
    watch_poll_seconds: float = 5.0

    # Polling configuration
    poll_interval_seconds: float = 2.0
    stage_timeout_seconds: int = 900

    # Retry backoff: a failed job waits retry_base_seconds * 2**(attempt-1) before rerunning
    retry_base_seconds: int = 30

    # Logging (LOG_LEVEL)
    log_level: str = "INFO"

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False

    def get_database_url(self) -> str:
        """Normalize database URL from postgresql:// to postgresql+psycopg://."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # type: ignore[call-arg]
