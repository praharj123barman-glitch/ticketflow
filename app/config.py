"""Central application configuration, loaded from environment variables.

Using pydantic-settings means every value is validated on startup and can be
overridden by an env var or the .env file — the standard 12-factor approach.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres connection (psycopg3 sync driver — keeps the FOR UPDATE logic easy to reason about)
    database_url: str = "postgresql+psycopg://ticketflow:ticketflow@localhost:5432/ticketflow"
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Booking domain rules
    hold_ttl_seconds: int = 600           # how long a seat hold survives (10 min checkout window)
    max_seats_per_booking: int = 8        # guard against one user grabbing a whole row

    # Payments (Stripe). Leave keys empty for offline dev: payment_service then
    # runs in a deterministic "fake" mode so the full flow is testable without
    # network/keys. Set test-mode keys (sk_test_..., whsec_...) for real Checkout.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    currency: str = "inr"
    # Post-payment return URLs are derived from public_base_url (see payment_service).

    # Email. Leave smtp_host empty for the dev backend (logs + in-memory outbox).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "TicketFlow <no-reply@ticketflow.dev>"

    # DB connection pool (PER gunicorn worker). N workers => up to
    # N*(pool_size+max_overflow) connections; keep under Postgres max_connections.
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Concurrency / infra
    lock_ttl_ms: int = 5000               # Redis lock auto-expiry (deadlock safety net)
    lock_acquire_timeout_ms: int = 2000   # how long we wait to grab a contended lock
    rate_limit_per_minute: int = 120      # per-client request budget on hot endpoints

    # Virtual waiting room (on-sale spike protection). Disabled by default so the
    # normal flow/tests are unaffected; set a LOW threshold to demo queueing.
    waitroom_enabled: bool = False
    waitroom_active_threshold: int = 100      # max concurrent admitted sessions per event
    waitroom_admit_batch: int = 20            # users admitted per tick
    waitroom_admit_interval_seconds: int = 5  # admitter tick cadence
    waitroom_session_ttl_seconds: int = 600   # admitted session lifetime (heartbeat-refreshed)

    environment: str = "development"

    # Public origin of the site (no trailing slash) — used to build absolute URLs
    # for OpenGraph/Twitter share tags, the sitemap, and canonical links so link
    # previews on WhatsApp/LinkedIn resolve correctly. Set to the prod domain on EC2.
    public_base_url: str = "http://localhost:5173"

    # When the API is served behind a path prefix (e.g. nginx routes /api/* to
    # it while serving the SPA at /), set root_path="/api" so the OpenAPI docs
    # generate correct URLs. Empty in local dev / CI.
    root_path: str = ""


settings = Settings()
