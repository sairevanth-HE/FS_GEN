from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    # Database Settings
    DATABASE_URL: str

    # LLM keys — at least one required (enforced in agents/base.py)
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # models — two tiers: smart for complex stages (design, solution, tests, fixes),
    # cheap for brush-up stages (skeleton scaffolding, problem statement, test critic).
    # ANTHROPIC_MODEL/OPENAI_MODEL are the smart tier (names kept for backwards compat).
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    OPENAI_MODEL: str = "gpt-5.4"
    ANTHROPIC_MODEL_CHEAP: str = "claude-haiku-4-5"
    OPENAI_MODEL_CHEAP: str = "gpt-4.1-mini"

    LOG_LEVEL: str = "INFO"

    # QOS: hard ceiling on total tokens spent per question. 0 (default) disables it.
    # NOTE: the per-agent counter sums input+output+cache tokens on EVERY tool-loop
    # iteration, so a normal question reads as 600k+ — set a ceiling accordingly
    # (e.g. 2_000_000) if you ever need a runaway guard.
    MAX_TOKENS_PER_QUESTION: int = 0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="allow"
    )


settings = Settings()
