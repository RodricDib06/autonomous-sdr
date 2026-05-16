import secrets
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # ignore unknown env vars (safe for CI)
        case_sensitive=False,    # DATABASE_URL == database_url == DATABASE_URL
    )

    # ── Database / Redis ───────────────────────────────────────────────────────
    DATABASE_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    APP_ENV: str = "development"

    # ── AI provider ────────────────────────────────────────────────────────────
    # "ollama" (default, free, local) | "groq" (free tier) | "claude" (production)
    AI_PROVIDER: str = "ollama"

    # Ollama — used when AI_PROVIDER=ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral"

    # Anthropic Claude — used when AI_PROVIDER=claude
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Groq — used when AI_PROVIDER=groq (free tier: 6 000 req/h, 500 k tok/min)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-70b-versatile"

    # ── Research / web search ─────────────────────────────────────────────────
    # Tavily — free: 1 000 searches/mo. Falls back to DuckDuckGo when unset.
    TAVILY_API_KEY: str = ""

    # ── Enrichment provider ────────────────────────────────────────────────────
    # "synthetic" (default, free) | "hunter" (real) | "pdl" (People Data Labs)
    ENRICHMENT_PROVIDER: str = "synthetic"
    HUNTER_API_KEY: str = ""
    PDL_API_KEY: str = ""
    CRUNCHBASE_API_KEY: str = ""

    # ── ICP Configuration ──────────────────────────────────────────────────────
    ICP_MIN_COMPANY_SIZE: int = 50
    ICP_MAX_COMPANY_SIZE: int = 500
    # Kept as str so pydantic-settings doesn't try to JSON-decode comma-separated values.
    # Use settings.icp_industries (the property below) to get the parsed list.
    ICP_INDUSTRIES: str = "SaaS,Technology,Software,FinTech,DevTools"
    ICP_MIN_SENIORITY: str = "Manager"

    @property
    def icp_industries(self) -> list[str]:
        return [s.strip() for s in self.ICP_INDUSTRIES.split(",") if s.strip()]

    # ── Performance ────────────────────────────────────────────────────────────
    MAX_CONCURRENT_LEADS: int = 3
    WORKER_BATCH_SIZE: int = 3

    # ── Auth — JWT ─────────────────────────────────────────────────────────────
    # Generate a stable key in production:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    # If unset, a random key is generated at startup — tokens are invalidated on restart.
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Auth — Initial admin seeded on first startup ───────────────────────────
    INITIAL_ADMIN_EMAIL: str = "admin@autonomoussdr.com"
    INITIAL_ADMIN_PASSWORD: str = "changeme123"

    # ── Webhook security ──────────────────────────────────────────────────────
    # Shared secret validated on every /ingest/* endpoint via X-Webhook-Secret.
    # Leave empty for open / demo mode.
    WEBHOOK_SECRET: str = ""

    # Seconds a pending lead can sit before the scheduler auto-requeues it.
    AUTO_PROCESS_DELAY_SECONDS: int = 60

    # ── CORS — production allowed origins ─────────────────────────────────────
    # Comma-separated exact origins. Localhost regex is always active in dev.
    # Example: https://sdr.mycompany.com,https://app.mycompany.com
    ALLOWED_ORIGINS: str = ""

    # ── Outreach / SMTP ────────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    OUTREACH_FROM_EMAIL: str = ""
    OUTREACH_SENDER_NAME: str = "Sales Team"

    # ── Booking — Cal.com ──────────────────────────────────────────────────────
    CAL_API_KEY: str = ""
    CAL_SCHEDULING_URL: str = ""
    CAL_EVENT_TYPE_ID: str = ""

    # ── CRM integrations ──────────────────────────────────────────────────────
    HUBSPOT_API_KEY: str = ""
    SALESFORCE_USERNAME: str = ""
    SALESFORCE_PASSWORD: str = ""
    SALESFORCE_SECURITY_TOKEN: str = ""
    PIPEDRIVE_API_KEY: str = ""

    # ── Conversational channels ───────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    UNIPILE_API_KEY: str = ""

    # ── App base URL ───────────────────────────────────────────────────────────
    APP_BASE_URL: str = ""

    # ── Notifications ─────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL: str = ""


settings = Settings()
