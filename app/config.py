import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # ── AI provider ────────────────────────────────────────────────────────────
    # "ollama" (default, free, local) | "claude" (production quality)
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "ollama")

    # Ollama — used when AI_PROVIDER=ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")

    # Anthropic Claude — used when AI_PROVIDER=claude
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Groq — used when AI_PROVIDER=groq (free tier: 6 000 req/h, 500 k tok/min)
    # Sign up at https://console.groq.com — no credit card for free tier
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    # ── Research / web search ─────────────────────────────────────────────────
    # Tavily — used by ResearchAgent for real web search (free: 1 000 searches/mo)
    # Sign up at https://tavily.com — no credit card for free tier
    # Without a key, DuckDuckGo is used as a free fallback (no sign-up needed)
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ── Enrichment provider ────────────────────────────────────────────────────
    # "synthetic" (default, free, heuristic) | "hunter" (real company data)
    ENRICHMENT_PROVIDER: str = os.getenv("ENRICHMENT_PROVIDER", "synthetic")

    # Hunter.io — used when ENRICHMENT_PROVIDER=hunter
    HUNTER_API_KEY: str = os.getenv("HUNTER_API_KEY", "")

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

    # ── Outreach / SMTP ────────────────────────────────────────────────────────
    # PoC: Gmail SMTP (free, 500 emails/day with an App Password)
    # PRODUCTION: replace host/port/user/password with SendGrid / Mailgun relay
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    OUTREACH_FROM_EMAIL: str = os.getenv("OUTREACH_FROM_EMAIL", "")
    OUTREACH_SENDER_NAME: str = os.getenv("OUTREACH_SENDER_NAME", "Sales Team")

    # ── Booking — Cal.com ──────────────────────────────────────────────────────
    # Free tier: https://cal.com  |  Self-hosted: https://github.com/calcom/cal.com
    CAL_API_KEY: str = os.getenv("CAL_API_KEY", "")
    CAL_SCHEDULING_URL: str = os.getenv("CAL_SCHEDULING_URL", "")  # e.g. https://cal.com/yourname/30min
    CAL_EVENT_TYPE_ID: str = os.getenv("CAL_EVENT_TYPE_ID", "")    # numeric ID from Cal.com dashboard

    # ── CRM integrations (all optional — mock logs when not configured) ─────────
    # HubSpot (free CRM tier available): https://developers.hubspot.com/docs/api/crm/contacts
    HUBSPOT_API_KEY: str = os.getenv("HUBSPOT_API_KEY", "")
    # Salesforce (developer org free): https://developer.salesforce.com/signup
    SALESFORCE_USERNAME: str = os.getenv("SALESFORCE_USERNAME", "")
    SALESFORCE_PASSWORD: str = os.getenv("SALESFORCE_PASSWORD", "")
    SALESFORCE_SECURITY_TOKEN: str = os.getenv("SALESFORCE_SECURITY_TOKEN", "")
    # Pipedrive (free trial): https://developers.pipedrive.com
    PIPEDRIVE_API_KEY: str = os.getenv("PIPEDRIVE_API_KEY", "")

    # ── Conversational channels (optional — mocked when not configured) ─────────
    # Twilio SMS: https://www.twilio.com/docs/sms
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    # Unipile (LinkedIn DM bridge): https://developer.unipile.com
    UNIPILE_API_KEY: str = os.getenv("UNIPILE_API_KEY", "")

    # ── Enrichment — People Data Labs ──────────────────────────────────────────
    # Free tier: 100 calls/month. Sign up: https://www.peopledatalabs.com/
    # Set ENRICHMENT_PROVIDER=pdl to activate
    PDL_API_KEY: str = os.getenv("PDL_API_KEY", "")

    # ── Enrichment — Crunchbase ────────────────────────────────────────────────
    # Basic API: $29/month. Sign up: https://data.crunchbase.com/
    # Without key, uses deterministic mock signals (great for demos)
    CRUNCHBASE_API_KEY: str = os.getenv("CRUNCHBASE_API_KEY", "")

    # ── App base URL (for tracking pixel URLs in emails) ──────────────────────
    # Set to your public URL in production, e.g. https://sdr.yourcompany.com
    # Leave empty in local dev — tracking pixels won't embed but app still works
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "")

    # ── Notifications ─────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")


settings = Settings()
