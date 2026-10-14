"""MPS 测试公共夹具：SQLite 临时库（默认）与 PostgreSQL 测试库（可选）。"""
import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import engine_kwargs


def require_test_pg(url: str) -> str:
    """校验 PG 测试库地址：库名必须以 test_ 开头或 _test 结尾（防误删生产库）。"""
    db_name = make_url(url).database or ""
    if not (db_name.startswith("test_") or db_name.endswith("_test")):
        raise pytest.UsageError(f"TEST_PG_URL 库名须以 test_ 开头或 _test 结尾（防误删），当前：{db_name}")
    return url


@pytest.fixture
async def sqlite_engine(tmp_path):
    from app.database import Base
    import app.models  # noqa: F401  注册全部模型

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(url, **engine_kwargs(url))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sqlite_session(sqlite_engine):
    session_factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def pg_session():
    url = os.getenv("TEST_PG_URL")
    if not url:
        pytest.skip("需要 TEST_PG_URL 环境变量")
    require_test_pg(url)
    from app.database import Base
    import app.models  # noqa: F401

    engine = create_async_engine(url, **engine_kwargs(url))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
