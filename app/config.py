from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://kqa:kqa@localhost:5432/kqa"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24
    top_k: int = 4
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 10
    max_file_size_mb: int = 10


settings = Settings()
