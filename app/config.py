import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # ICP Configuration
    ICP_MIN_COMPANY_SIZE: int = int(os.getenv("ICP_MIN_COMPANY_SIZE", "50"))
    ICP_MAX_COMPANY_SIZE: int = int(os.getenv("ICP_MAX_COMPANY_SIZE", "500"))
    ICP_INDUSTRIES: list[str] = os.getenv(
        "ICP_INDUSTRIES", "SaaS,Technology,Software,FinTech,DevTools"
    ).split(",")
    ICP_MIN_SENIORITY: str = os.getenv("ICP_MIN_SENIORITY", "Manager")

    # Performance Configuration
    MAX_CONCURRENT_LEADS: int = int(os.getenv("MAX_CONCURRENT_LEADS", "3"))
    WORKER_BATCH_SIZE: int = int(os.getenv("WORKER_BATCH_SIZE", "3"))

    # Auth — JWT
    # A strong random key is generated at import time when SECRET_KEY is not set.
    # This means tokens are invalidated on restart in development.
    # In production, always set SECRET_KEY explicitly in the environment.
    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_hex(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Auth — Initial admin seeded on first startup when no users exist
    INITIAL_ADMIN_EMAIL: str = os.getenv("INITIAL_ADMIN_EMAIL", "admin@autonomoussdr.com")
    INITIAL_ADMIN_PASSWORD: str = os.getenv("INITIAL_ADMIN_PASSWORD", "changeme123")


settings = Settings()
