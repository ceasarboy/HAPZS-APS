"""应用配置模块，使用 pydantic-settings 从环境变量和 .env 文件读取配置。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置类，从 .env 文件和环境变量加载配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # HAP 鉴权配置（默认为空，通过设置页面配置或 .env 文件提供）
    HAP_APP_ID: str = ""
    HAP_APPKEY: str = ""
    HAP_SIGN: str = ""
    HAP_BASE_URL: str = "https://api.mingdao.com"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # PostgreSQL 配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/aps_hap"

    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # OpenAPS 求解引擎配置
    OPENAPS_HOME: str = "./openaps"
    SOLVER_ENGINE: str = "ortools"  # 可选: ortools / gock

    # API 安全配置
    API_KEY: str = "aps-hap-secret-key"


# 全局配置实例
settings = Settings()
