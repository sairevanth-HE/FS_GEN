from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    # Database Settings
    DATABASE_URL: str

    # LLM keys — at least one required (enforced in agents/base.py)
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # models
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    OPENAI_MODEL: str = "gpt-5.4"

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="allow"
    )


settings = Settings()
