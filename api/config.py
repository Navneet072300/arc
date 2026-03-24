from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/serverless_pg"

    # JWT
    SECRET_KEY: str = "change-me-to-a-32-byte-random-hex-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Kubernetes
    K8S_IN_CLUSTER: bool = False
    KUBECONFIG_PATH: str = ""
    ENVIRONMENT: str = "dev"   # dev | prod
    STORAGE_CLASS: str = "standard"

    # Metering
    METERING_INTERVAL_SECS: int = 60


settings = Settings()
