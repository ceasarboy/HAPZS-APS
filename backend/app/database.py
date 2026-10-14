"""数据库配置模块，使用 SQLAlchemy 2.0 异步引擎（支持 PostgreSQL 与本地 SQLite 双模式）。"""

from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def is_sqlite(url: str) -> bool:
    """判断是否为 SQLite 数据库地址（本地单机模式）。"""
    return url.startswith("sqlite")


def engine_kwargs(url: str) -> dict:
    """根据数据库类型返回引擎参数（SQLite 不支持连接池参数）。"""
    if is_sqlite(url):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}


def _ensure_sqlite_dir(url: str) -> None:
    """确保 SQLite 文件所在目录存在。"""
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite") and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    **engine_kwargs(settings.DATABASE_URL),
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""
    pass


async def init_schema(target_engine=None, url: str | None = None) -> None:
    """初始化数据库结构。

    本地 SQLite 模式：自动建表（create_all，零运维）；
    服务器 PostgreSQL 模式：由 Alembic 迁移管理，此处不做任何事。
    """
    url = url or settings.DATABASE_URL
    if not is_sqlite(url):
        return
    import app.models  # noqa: F401  确保全部模型注册到 Base.metadata

    _ensure_sqlite_dir(url)
    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """获取数据库会话，用于 FastAPI 依赖注入。

    Yields:
        AsyncSession: 异步数据库会话
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
