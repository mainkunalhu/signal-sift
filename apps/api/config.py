"""Central settings loaded from repo-root .env (never commit .env)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    groq_api_key: str = ""
    groq_planner_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "openai/gpt-oss-20b"
    groq_fallback_model: str = "qwen/qwen3-32b"
    database_url: str = ""
    searxng_url: str = "https://searx.be"
    tavily_api_key: str = ""
    max_concurrent_researchers: int = 4
    phoenix_endpoint: str = "https://app.phoenix.arize.com/v1/traces"
    phoenix_api_key: str = ""
    api_port: int = 8000


settings = Settings()
