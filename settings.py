from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -------------------------------------------------
    # Pydantic v2 configuration
    # -------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",          # Prevent accidental unknown env vars
        case_sensitive=False,    # ENV vars are case-insensitive
    )

    APP_NAME: str = "XBOS Kernel"

    # -------------------------------------------------
    # JWT settings
    # -------------------------------------------------
    JWT_SECRET: str = "supersecretkey_change_me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # -------------------------------------------------
    # Database (PostgreSQL)
    # -------------------------------------------------
    DATABASE_URL: str = "postgresql+psycopg2://postgres:Becky@8282@localhost:5432/xbos"

    # -------------------------------------------------
    # Gateway Integration (XafPay)
    # -------------------------------------------------
    GATEWAY_BASE_URL: str = "http://localhost:3000"
    GATEWAY_API_KEY: str  # MUST exist in .env

    # -------------------------------------------------
    # DEV SUPPORT
    # -------------------------------------------------
    ENV: str = "production"
    DEV_TENANT_CODE: str | None = None


settings = Settings()
