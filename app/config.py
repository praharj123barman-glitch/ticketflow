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
    seat_hold_seconds: int = 120          # how long a temporary seat hold survives
    max_seats_per_booking: int = 8        # guard against one user grabbing a whole row

    # Concurrency / infra
    lock_ttl_ms: int = 5000               # Redis lock auto-expiry (deadlock safety net)
    lock_acquire_timeout_ms: int = 2000   # how long we wait to grab a contended lock
    rate_limit_per_minute: int = 120      # per-client request budget on hot endpoints

    environment: str = "development"

    # When the API is served behind a path prefix (e.g. nginx routes /api/* to
    # it while serving the SPA at /), set root_path="/api" so the OpenAPI docs
    # generate correct URLs. Empty in local dev / CI.
    root_path: str = ""


settings = Settings()
