"""启动行为：PG 模式下 Redis 初始化失败应中止启动（fail-fast）。"""
import pytest

import app.main as main_mod


async def test_lifespan_pg_redis_failure_aborts(monkeypatch):
    async def boom():
        raise ConnectionError("refused")

    monkeypatch.setattr(main_mod.settings, "DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(main_mod, "init_redis", boom)

    with pytest.raises(ConnectionError):
        async with main_mod.lifespan(main_mod.app):
            pass
