"""MPS 测试公共夹具：SQLite 临时库（默认）与 PostgreSQL 测试库（可选）。"""
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def sqlite_engine(tmp_path):
    from app.database import Base
    import app.models  # noqa: F401  注册全部模型

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(url)
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
    if "test" not in url.lower():
        pytest.skip("TEST_PG_URL 必须指向测试库（地址含 test）")
    from app.database import Base
    import app.models  # noqa: F401

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
