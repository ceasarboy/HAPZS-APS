"""迁移与模型漂移守卫：migrated SQLite schema 必须与 create_all 等价。"""
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.models.mps import (
    HapConnection, HapFieldMapping, HapMapping, Order, OrderOperation,
    ProcessMaster, ProcessRoute, ProcessSet, PriorityBatch, PriorityLog,
    ScheduleAllocation, ScheduleBatch, SystemParam,
)

MPS_TABLES = [
    "process_masters", "process_sets", "process_routes", "orders", "order_operations",
    "system_params", "schedule_batches", "schedule_allocations",
    "priority_logs", "priority_batches",
    "hap_connections", "hap_mappings", "hap_field_mappings",
]

BACKEND_DIR = Path(__file__).resolve().parents[2]
# 历史常量：62ad14d88051 迁移的父版本（旧链末端）。旧迁移面向 PG 未在 SQLite 上验证，
# 因此测试用 stamp 跳过旧链、只执行 62ad14d88051 及其后的新迁移；
# 漂移守卫覆盖 stamp 之后的全部 revision（新增迁移会自动纳入）。
OLD_CHAIN_HEAD = "b2c3d4e5f6g7"
FIRST_REWORK_REVISION = "62ad14d88051"


def _alembic_cfg() -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _create_all_db(path: Path):
    from app.database import Base
    import app.models  # noqa: F401

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _migrated_db(path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    cfg = _alembic_cfg()
    first = ScriptDirectory.from_config(cfg).get_revision(FIRST_REWORK_REVISION)
    assert first is not None, "找不到首个 MPS 迁移 revision"
    assert first.down_revision == OLD_CHAIN_HEAD, "旧链末端常量已过期，请同步 OLD_CHAIN_HEAD"
    command.stamp(cfg, OLD_CHAIN_HEAD)
    command.upgrade(cfg, "head")
    return create_engine(f"sqlite:///{path}")


def _schema(engine) -> dict:
    insp = inspect(engine)
    result = {}
    for name in MPS_TABLES:
        cols = {
            c["name"]: (str(c["type"]), bool(c["nullable"]), bool(c["primary_key"]), c.get("default"))
            for c in insp.get_columns(name)
        }
        uniques = {frozenset(u["column_names"]) for u in insp.get_unique_constraints(name)}
        indexes = {i["name"]: tuple(i["column_names"]) for i in insp.get_indexes(name)}
        result[name] = (cols, uniques, indexes)
    return result


def test_migration_matches_models(tmp_path, monkeypatch):
    engine_a = _create_all_db(tmp_path / "a.db")
    engine_b = _migrated_db(tmp_path / "b.db", monkeypatch)
    try:
        schema_a = _schema(engine_a)
        schema_b = _schema(engine_b)
        for table in MPS_TABLES:
            assert schema_a[table] == schema_b[table], f"schema 漂移: {table}"
        migrated_tables = set(inspect(engine_b).get_table_names()) - {"alembic_version"}
        assert migrated_tables == set(MPS_TABLES), "新迁移引入了未纳入守卫的表，请更新 MPS_TABLES"
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_alembic_single_head():
    heads = ScriptDirectory.from_config(_alembic_cfg()).get_heads()
    assert len(heads) == 1
