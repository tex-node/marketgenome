from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "local"
    log_level: str = "INFO"
    public_url: str = "https://genome.fothlog.com"
    max_upload_bytes: int = 50_000_000
    max_sync_window_candidates: int = 100_000
    database_url: str = (
        "postgresql+psycopg://market_genome:market_genome@localhost:5432/market_genome"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MARKET_GENOME_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
