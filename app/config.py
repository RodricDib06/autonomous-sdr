import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    ICP_MIN_COMPANY_SIZE: int = int(os.getenv("ICP_MIN_COMPANY_SIZE", "50"))
    ICP_MAX_COMPANY_SIZE: int = int(os.getenv("ICP_MAX_COMPANY_SIZE", "500"))
    ICP_INDUSTRIES: list[str] = os.getenv(
        "ICP_INDUSTRIES", "SaaS,Technology,Software,FinTech,DevTools"
    ).split(",")
    ICP_MIN_SENIORITY: str = os.getenv("ICP_MIN_SENIORITY", "Manager")


settings = Settings()
