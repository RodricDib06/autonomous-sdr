import os
import secrets
from pydantic import Field, model_validator
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
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

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

    # Run the LangGraph worker inside the API process, on its own thread,
    # instead of as a separate `python -m app.worker.lead_worker` process.
    # Intended for single-instance hosts that charge for (or don't offer) a
    # second always-on process — Render's free tier has no background worker.
    # Leave false wherever the worker can be its own service: separate
    # processes scale and fail independently, which is what you want in
    # production.
    RUN_WORKER_IN_PROCESS: bool = False

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

    # ── Email verification (pre-send deliverability gate) ─────────────────────
    # Syntax + disposable-domain + role-account + MX checks before any send.
    EMAIL_VERIFICATION_ENABLED: bool = True
    # SMTP RCPT probe (connects to the recipient's MX on port 25). Off by
    # default: many hosts block outbound 25 and some MXs greylist probes.
    EMAIL_VERIFICATION_SMTP_PROBE: bool = False
    # Re-verify a lead's address after this many days (0 = trust forever).
    EMAIL_VERIFICATION_TTL_DAYS: int = 7

    # ── Prospecting (the agent sources its own leads) ──────────────────────────
    # "synthetic" (default, deterministic demo) | "pdl" (People Data Labs Person
    # Search — reuses PDL_API_KEY)
    PROSPECTING_PROVIDER: str = "synthetic"
    # Hard budget guardrails, enforced in code before any insert
    PROSPECTING_MAX_LEADS_PER_DAY: int = 100
    # Candidates scoring below this (deterministic BANT, same as backtests)
    # are rejected as low_score
    PROSPECTING_MIN_SCORE: float = 0.3

    # ── OAuth mailboxes (Gmail API / Microsoft Graph) ──────────────────────────
    # Google Cloud OAuth client (Gmail API enabled, scopes: gmail.send, gmail.modify)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Entra ID app registration (delegated Mail.Send, Mail.ReadWrite, offline_access)
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = "common"

    # ── Outreach / SMTP ────────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    OUTREACH_FROM_EMAIL: str = ""
    OUTREACH_SENDER_NAME: str = "Sales Team"

    # ── Privacy / data retention ───────────────────────────────────────────────
    # Erase non-converted leads older than this many days (0 = keep forever).
    # Converted/won leads are business records and are exempt.
    DATA_RETENTION_DAYS: int = 0

    # ── Autonomy dial ──────────────────────────────────────────────────────────
    # Default outreach autonomy for orgs that haven't chosen one (Settings → Autonomy):
    #   draft   — agent writes emails, sends nothing (copy-out only)
    #   approve — every email waits in the approval queue before sending
    #   auto    — full autonomy: step 1 sends immediately, follow-ups on schedule
    DEFAULT_AUTONOMY_MODE: str = "auto"

    # ── Outreach guardrails (compliance & deliverability) ─────────────────────
    # Max emails sent in any rolling 24h window — protects sender reputation
    OUTREACH_DAILY_SEND_LIMIT: int = 200
    # Only send between these hours (UTC). Cold email at 3 a.m. reads as spam.
    OUTREACH_SEND_WINDOW_START: int = 8
    OUTREACH_SEND_WINDOW_END: int = 18
    # Skip Saturday/Sunday sends
    OUTREACH_WEEKDAYS_ONLY: bool = True

    # ── Booking — Cal.com ──────────────────────────────────────────────────────
    CAL_API_KEY: str = ""
    CAL_SCHEDULING_URL: str = ""
    CAL_EVENT_TYPE_ID: str = ""

    # ── CRM integrations ──────────────────────────────────────────────────────
    # HubSpot OAuth app (bidirectional sync): create at developers.hubspot.com,
    # scopes crm.objects.contacts.read/write + crm.objects.deals.read, redirect
    # {APP_BASE_URL}/crm/hubspot/callback. The client secret also validates
    # webhook signatures (X-HubSpot-Signature-v3).
    HUBSPOT_CLIENT_ID: str = ""
    HUBSPOT_CLIENT_SECRET: str = ""
    # Legacy private-app token — outbound-only fallback when OAuth isn't connected
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

    # ── Demo mode ──────────────────────────────────────────────────────────────
    # Comma-separated emails whose sessions are read-only (GET/HEAD/OPTIONS
    # only) — lets a public demo login be posted safely in the README.
    DEMO_READONLY_EMAILS: str = ""

    @property
    def demo_readonly_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.DEMO_READONLY_EMAILS.split(",") if e.strip()}

    # ── Notifications ─────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL: str = ""

    @model_validator(mode="after")
    def _default_app_base_url(self):
        """
        Fall back to the host's own public URL when APP_BASE_URL is unset.

        Unsubscribe links, tracking pixels, and OAuth callbacks are all built
        from APP_BASE_URL; left empty they silently degrade (a sequence sends
        without the RFC 8058 unsubscribe header). Render injects its public
        URL into the environment, so on Render the value is inferable and
        nobody has to paste a domain back into config after the first deploy.
        """
        if not self.APP_BASE_URL:
            external = os.getenv("RENDER_EXTERNAL_URL")
            if not external:
                hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
                external = f"https://{hostname}" if hostname else ""
            if external:
                self.APP_BASE_URL = external.rstrip("/")
        return self


settings = Settings()
