"""双库引擎参数与连通性测试。"""
import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
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
    db_name = make_url(url).database or ""
    assert db_name.startswith("test_") or db_name.endswith("_test"), (
        f"TEST_PG_URL 库名须以 test_ 开头或 _test 结尾（防误删），当前：{db_name}"
    )
    engine = create_async_engine(url, **engine_kwargs(url))
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    await engine.dispose()


async def test_init_schema_creates_tables_with_engine(tmp_path):
    from app.database import Base, init_schema

    db_path = tmp_path / "nested" / "dir" / "x.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, **engine_kwargs(url))
    await init_schema(target_engine=engine, url=url)
    assert db_path.exists()
    async with engine.connect() as conn:
        tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    assert set(Base.metadata.tables).issubset(tables)
    await engine.dispose()


async def test_init_schema_idempotent(tmp_path):
    from app.database import init_schema

    url = f"sqlite+aiosqlite:///{tmp_path / 'idem.db'}"
    engine = create_async_engine(url, **engine_kwargs(url))
    await init_schema(target_engine=engine, url=url)
    await init_schema(target_engine=engine, url=url)
    await engine.dispose()


async def test_init_schema_url_without_engine_rejected(monkeypatch):
    from app.core.config import settings
    from app.database import init_schema

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    with pytest.raises(ValueError):
        await init_schema(url="sqlite+aiosqlite:///./definitely-other.db")


async def test_init_schema_pg_url_noop():
    from app.database import init_schema

    # PG 地址应为早退 no-op（不连接、不建表）
    await init_schema(url="postgresql+asyncpg://u:p@nonexistent-host/none_test")
