"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration from environment variables."""

    # Database URL (required, no default)
    database_url: str

    # API configuration
    api_port: int = 8000
    log_level: str = "INFO"

    # CORS configuration (comma-separated list)
    cors_origins: str = ""

    # Auth (JWT session tokens and login rate limit)
    jwt_secret: str = Field(..., min_length=32)
    jwt_ttl_minutes: int = 480
    login_max_failures: int = 5
    login_window_seconds: int = 900

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False

    def get_cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        if not self.cors_origins.strip():
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
