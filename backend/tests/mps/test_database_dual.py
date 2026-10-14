"""双库引擎参数与连通性测试。"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import engine_kwargs, is_sqlite


def test_is_sqlite_detection():
    assert is_sqlite("sqlite+aiosqlite:///./data/mps.db") is True
    assert is_sqlite("postgresql+asyncpg://u:p@h/db") is False


def test_engine_kwargs_no_pool_for_sqlite():
    kw = engine_kwargs("sqlite+aiosqlite:///./data/mps.db")
    assert "pool_size" not in kw
    assert kw["connect_args"]["check_same_thread"] is False


def test_engine_kwargs_pool_for_pg():
    kw = engine_kwargs("postgresql+asyncpg://u:p@h/db")
    assert kw["pool_size"] == 5
    assert kw["pool_pre_ping"] is True


async def test_sqlite_engine_connect(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    engine = create_async_engine(url, **engine_kwargs(url))
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_PG_URL"), reason="需要 TEST_PG_URL 环境变量")
async def test_pg_engine_connect():
    url = os.environ["TEST_PG_URL"]
    assert "test" in url.lower(), "TEST_PG_URL 必须指向测试库（地址含 test）以防误删数据"
    engine = create_async_engine(url, **engine_kwargs(url))
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    await engine.dispose()
