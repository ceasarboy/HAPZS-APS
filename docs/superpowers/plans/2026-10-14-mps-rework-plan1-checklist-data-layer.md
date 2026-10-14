# MPS 改造 计划 1/6：Check-list 提取与数据层地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出 MPS 业务逻辑 Check-list（编号规则+测试用例映射），并建立新 MPS 数据层地基：13 张核心表、SQLite/PostgreSQL 双库、种子数据导入、本地单机可启动。

**Architecture:** SQLAlchemy 2.0 异步模型（继承 SyncBase 出箱字段）新增 `app/models/mps.py`；数据库引擎按 URL 自适应 SQLite(aiosqlite)/PostgreSQL(asyncpg)；种子数据由 mps-web `seed.json` 一次性转换固化为仓库内 JSON；开发流程遵循 SDD（先 check-list，后逐条测试用例）。

**Tech Stack:** Python 3.11+（本机 3.14）、FastAPI、SQLAlchemy 2.0 异步、Alembic、pytest + pytest-asyncio、aiosqlite、openpyxl、python-docx。

**计划总览（本文件仅为计划 1）：**
| 计划 | 内容 | 状态 |
|---|---|---|
| 1 | Check-list 提取 + 数据层地基（本文件） | 执行中 |
| 2 | 核算内核（周期/成品率/投料/通量/瓶颈/爬坡/交付/周负荷，1:1 移植 + 官方算例对齐） | 待编制 |
| 3 | 排产内核（工序级需求分解、解码层、优先级引擎、策略、GA 核心、CP-SAT 可选、确定性基准） | 待编制 |
| 4 | 明道云（加密连接、映射设置后端、表单读取自动匹配、通用同步引擎） | 待编制 |
| 5 | 前端（六视图 + 映射页 + 菜单整合，React/TS/AntD） | 待编制 |
| 6 | 集成收尾（Excel 导入导出、部署、离线包、端到端验收） | 待编制 |

**约束：**
- `D:\MPS` 只读，任何步骤不得修改其中文件（`mps-web` 仅作为移植参照）；
- 全部代码在 `D:\aps-hap`；
- 遵循 `CLAUDE.md`：简单优先、外科手术式改动、每步可验证。

**参考（执行前建议先读）：**
- 设计规格：`docs/superpowers/specs/2026-10-14-mps-rework-design.md`
- 移植参照：`D:\MPS\mps-web\src\consts.js`（只读）、`D:\MPS\mps-web\seed.json`（只读）、`D:\MPS\mps-web\sample_orders.json`（只读）
- MPS 资料：`D:\MPS\封测中心产线成套工艺计算逻辑说明书-V1.6.docx`、`D:\MPS\封装架构与成套工艺清单-V1.7.xlsx`、`D:\MPS\模块工单-1007测试样本.xlsx`

---

### Task 0: 基线版本控制

**Files:**
- Modify: `.gitignore`

- [ ] **Step 0.1: 初始化 git 并追加忽略项**

本目录当前不是 git 仓库（`git rev-parse --is-inside-work-tree` 报错）。若不希望使用 git，可跳过本任务及后续所有"提交"步骤。

在 `.gitignore` 末尾追加：
```
# 离线部署包与临时文件
offline/
backend/.tmp/
backend/data/
```

- [ ] **Step 0.2: 初始化并基线提交**

（在仓库根目录执行）
```bash
git init
git add -A
git commit -m "chore: 基线快照（改造前）"
```
Expected: `git status` 干净；`git log --oneline` 显示 1 条提交。

---

### Task 1: MPS 业务逻辑 Check-list 提取（SDD 第一交付物）

**Files:**
- Create: `backend/tools/extract_mps_docs.py`
- Create: `docs/checklists/mps-logic-checklist.md`
- 临时产物（不入库）：`backend/.tmp/mps-extract/*.md`

- [ ] **Step 1.1: 编写提取脚本**

创建 `backend/tools/extract_mps_docs.py`（只读 MPS 目录，输出到 `backend/.tmp/mps-extract/`）：

```python
"""从 D:\MPS 提取 docx/xlsx 文本，供编制 check-list 使用（只读 MPS 目录）。

用法：在 backend 目录执行  python tools/extract_mps_docs.py
输出：backend/.tmp/mps-extract/<原名>.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MPS_DIR = Path(r"D:\MPS")
OUT_DIR = Path(__file__).resolve().parents[1] / ".tmp" / "mps-extract"


def extract_docx(path: Path, out: Path) -> None:
    import docx

    doc = docx.Document(str(path))
    lines: list[str] = []
    for p in doc.paragraphs:
        if p.text.strip():
            lines.append(p.text)
    for ti, table in enumerate(doc.tables):
        lines.append(f"\n[表格 {ti + 1}]")
        for row in table.rows:
            lines.append(" | ".join(c.text.replace("\n", " ") for c in row.cells))
    out.write_text("\n".join(lines), encoding="utf-8")


def extract_xlsx(path: Path, out: Path) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"\n===== 工作表: {ws.title} (rows={ws.max_row}, cols={ws.max_column}) =====")
        for row in ws.iter_rows(values_only=True):
            if all(v is None for v in row):
                continue
            lines.append(" | ".join("" if v is None else str(v) for v in row))
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in MPS_DIR.glob("*.docx"):
        extract_docx(f, OUT_DIR / (f.stem + ".md"))
        print("extracted:", f.name)
    for f in MPS_DIR.glob("*.xlsx"):
        extract_xlsx(f, OUT_DIR / (f.stem + ".md"))
        print("extracted:", f.name)


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.2: 运行提取**

（在 `backend` 目录）
```powershell
python tools/extract_mps_docs.py
```
Expected: 打印 3 个文件名；`backend/.tmp/mps-extract/` 下生成 3 个 `.md` 文件：
- `封测中心产线成套工艺计算逻辑说明书-V1.6.md`（含表格）
- `封装架构与成套工艺清单-V1.7.md`（多个工作表）
- `模块工单-1007测试样本.md`

- [ ] **Step 1.3: 编制 Check-list 文档**

创建 `docs/checklists/mps-logic-checklist.md`。逐条通读三份提取文件，按下列格式穷尽整理业务规则：

```markdown
# MPS 业务逻辑 Check-list（SDD 基准清单）

说明：每条规则对应至少一个测试用例；测试命名规则 `tests/mps/test_kernel_<分类>.py::test_<编号小写>_<简述>`，
状态：待实现 / 通过 / 阻塞(疑点)。

## 分类编码
- CALC 核算公式（周期/成品率/投料/通量/瓶颈）
- CYCLE 周期类（单件/加急/分部件/爬坡）
- YIELD 成品率/放量比/投料量
- FLUX 通量/瓶颈/DB-WB分流/折算系数
- DELIVERY 交付周期/最晚投料日/缓冲
- LOAD 周负荷/瓶颈占用/判定阈值
- PRIO 优先级引擎（6因子/P0-P3/置顶/拖拽）
- SCHED 排产约束（产能/齐套/串行/分配/分部件）
- SYNC 明道云映射与同步
- DB 双库与数据一致性
- UI 前端视图行为

## 清单

| 编号 | 规则描述 | 来源 | 预期结果 | 测试用例 | 状态 |
|---|---|---|---|---|---|
| CHK-CYCLE-001 | 加急压缩 ΔT：T单件≤5→1天、6~10→2天、>10→3天；T加急=max(T单件−ΔT, 1) | V1.6 加急单件周期 | 分段正确、不低于1天 | tests/mps/test_kernel_cycle.py::test_chk_cycle_001_urgent_delta_tiers | 待实现 |
| CHK-CYCLE-002 | 封盖类工序（模块封盖/组件激光封盖）无水汽要求时周期 2→1 天 | V1.6 / V1.7 Y列 | vapor_cap_cut 参数生效 | tests/mps/test_kernel_cycle.py::test_chk_cycle_002_vapor_cap | 待实现 |
| CHK-FLUX-001 | 模块级 DB 分流阈值 20 只：<20 用半自动（通量2000）、≥20 用自动（通量6000） | V1.6 分流 / V1.7 主数据 | pickMode 结果正确 | tests/mps/test_kernel_flux.py::test_chk_flux_001_db_split | 待实现 |
| CHK-CALC-001 | M02-2D 官方算例：T单件=6、放量比=1.052、投料=1052、批量周期=16、交付=17、瓶颈占用=11、最晚投料日=12/14 | V1.6 算例 | 数值全部一致 | tests/mps/test_kernel_official.py::test_chk_calc_001_m02_2d | 待实现 |
```

**穷尽性要求（完成判据）：**
1. V1.6 逻辑书每个编号小节均有 ≥1 条目：单件周期/分部件/加急/成品率（综合/装配/检验三率口径）/放量比/投料量/产出校核/分流/折算系数/通量/瓶颈/爬坡/交付/最晚投料/瓶颈占用/周负荷/判定阈值/参数表/职责分工；
2. V1.7 清单每个输出列（K/L 周期、I 成品率、J 放量比、W/X 爬坡、Y 水汽、AB 瓶颈、AC~AF 批量周期口径等）均有解读条目；
3. 工单样本全部 24 列均有字段条目（含"排产优先级""物料齐套时间""第2组特征"）；
4. 疑点清单每项 ≥2 条（参数两档取值）：①WB自动通量 12000 vs 20000；②批量项取整（ceil vs 不取整）；③订单缓冲 1 天是否计入；④爬坡触发（首单 vs 首单/复线/变更首件）；⑤BOM 特征唯一数据源（工单行 vs 采集表）；
5. 预估 90~120 条；若 <90 条，对照提取文件重新扫查遗漏；
6. 编号全局唯一，每条"测试用例"列有命名（允许"待实现"状态）。

- [ ] **Step 1.4: 核对与提交**

```bash
git add docs/checklists/mps-logic-checklist.md backend/tools/extract_mps_docs.py
git commit -m "docs: MPS 业务逻辑 check-list 与提取工具"
```

---

### Task 2: 依赖、pytest 配置与双库引擎

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Modify: `backend/app/database.py`
- Create: `backend/tests/mps/__init__.py`
- Create: `backend/tests/mps/conftest.py`
- Create: `backend/tests/mps/test_database_dual.py`

- [ ] **Step 2.1: 追加依赖**

在 `backend/requirements.txt` 末尾追加：
```
aiosqlite>=0.20
pytest>=8.0
pytest-asyncio>=0.24
```
（在 `backend` 目录）`pip install -r requirements.txt`

- [ ] **Step 2.2: pytest 配置**

创建 `backend/pytest.ini`：
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

创建空文件 `backend/tests/mps/__init__.py`。

- [ ] **Step 2.3: 编写失败测试（双库引擎）**

创建 `backend/tests/mps/test_database_dual.py`：
```python
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
```

- [ ] **Step 2.4: 运行测试确认失败**

（在 `backend` 目录）
```powershell
python -m pytest tests/mps/test_database_dual.py -v
```
Expected: FAIL —— `ImportError: cannot import name 'engine_kwargs' from 'app.database'`。

- [ ] **Step 2.5: 改造 `backend/app/database.py`**

将文件开头（engine 创建部分）替换为下述完整内容（`get_db` 函数保持不变，保留在文件末尾）：

```python
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
```

- [ ] **Step 2.6: 创建测试夹具 `backend/tests/mps/conftest.py`**

```python
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
```

- [ ] **Step 2.7: 运行测试确认通过**

```powershell
python -m pytest tests/mps/test_database_dual.py -v
```
Expected: 4 passed, 1 skipped（PG 未配置时）。

- [ ] **Step 2.8: 提交**

```bash
git add backend/requirements.txt backend/pytest.ini backend/tests/mps backend/app/database.py
git commit -m "feat(db): 双库引擎（SQLite/PG）与 pytest 基础设施"
```

---

### Task 3: 新 MPS ORM 模型（13 张表）

**Files:**
- Create: `backend/app/models/mps.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/mps/test_mps_models.py`

- [ ] **Step 3.1: 编写失败测试**

创建 `backend/tests/mps/test_mps_models.py`：
```python
"""MPS 新模型：建表、约束与字段冒烟测试。"""
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models.mps import (
    HapFieldMapping, HapMapping, Order, OrderOperation, ProcessMaster,
    ProcessRoute, ProcessSet, SystemParam,
)

EXPECTED_TABLES = {
    "process_masters", "process_sets", "process_routes", "orders", "order_operations",
    "system_params", "schedule_batches", "schedule_allocations",
    "priority_logs", "priority_batches",
    "hap_connections", "hap_mappings", "hap_field_mappings",
}


async def test_mps_tables_created(sqlite_engine):
    names = await sqlite_engine.run_sync(lambda conn: inspect(conn).get_table_names())
    assert EXPECTED_TABLES.issubset(set(names))


async def test_order_no_unique(sqlite_session):
    sqlite_session.add(Order(order_no="T-1", product="模块-01", code="M02-2D", qty=10))
    await sqlite_session.commit()
    sqlite_session.add(Order(order_no="T-1", product="模块-01", code="M02-2D", qty=10))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_process_route_unique_code_seq(sqlite_session):
    sqlite_session.add(ProcessRoute(code="X-1", seq=1, step_raw="DB", step_std="DB", level="模块级"))
    await sqlite_session.commit()
    sqlite_session.add(ProcessRoute(code="X-1", seq=1, step_raw="DB", step_std="DB", level="模块级"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_order_features_json_roundtrip(sqlite_session):
    sqlite_session.add(
        Order(order_no="T-2", product="模块-02", code="M02-2D", qty=5,
              features={"N_die": 60, "N_wire": 60, "Y_die": 2}, kit_date=None)
    )
    await sqlite_session.commit()
    row = (await sqlite_session.execute(select(Order).where(Order.order_no == "T-2"))).scalar_one()
    assert row.features["N_die"] == 60


async def test_process_master_unique_triple(sqlite_session):
    sqlite_session.add(ProcessMaster(level="模块级", op="DB", mode="自动DB"))
    await sqlite_session.commit()
    sqlite_session.add(ProcessMaster(level="模块级", op="DB", mode="自动DB"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_system_param_key_unique(sqlite_session):
    sqlite_session.add(SystemParam(key="week_days", value="6"))
    await sqlite_session.commit()
    sqlite_session.add(SystemParam(key="week_days", value="5"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()
```

- [ ] **Step 3.2: 运行测试确认失败**

```powershell
python -m pytest tests/mps/test_mps_models.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.mps'`。

- [ ] **Step 3.3: 创建 `backend/app/models/mps.py`**

```python
"""MPS 封测业务数据模型（新业务核心表）。

- 全部继承 SyncBase：id/hap_row_id/sync_status/synced_at/created_at/updated_at
- 与旧计划类表互不冲突（旧表在后续计划中被替换，数据可删）
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import SyncBase


class ProcessMaster(SyncBase):
    """工序主数据（级别|工序|模式 唯一）。"""

    __tablename__ = "process_masters"
    __table_args__ = (UniqueConstraint("level", "op", "mode", name="uq_process_master"),)

    level: Mapped[str] = mapped_column(String(20), comment="产品级别（芯片级/模块级/组件级）")
    op: Mapped[str] = mapped_column(String(50), comment="工序名称（规范名）")
    mode: Mapped[str] = mapped_column(String(20), default="/", comment="生产模式（半自动/自动//）")
    cycle: Mapped[float] = mapped_column(Float, default=1, comment="基准装配周期（天）")
    yield_assembly: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次装配合格率（存档）")
    yield_inspect: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次检验合格率（存档）")
    yield_overall: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合成品率（纳入计算）")
    cap_station: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单工位日产能")
    stations: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工位数")
    flux_base: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基准均值通量（单工位产能×工位数）")
    flux_peak: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基准峰值通量（均值×峰值系数）")
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="核算单位（如 颗/天，植球数N_b）")
    feature: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="特征参数名（如 N_b）")
    split_rule: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="分流规则说明")
    split_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="分流阈值（只）")
    cycle_note: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="周期调节说明")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class ProcessSet(SyncBase):
    """成套工艺主数据（工艺代号唯一，24 套 D01~C11）。"""

    __tablename__ = "process_sets"

    code: Mapped[str] = mapped_column(String(50), unique=True, comment="工艺代号（含版本，主键含义）")
    form: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="产品形态")
    arch: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="封装架构")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="成套工艺名称")
    feature: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="特征说明")
    version: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="版本号")
    route_text: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="路线原文")
    owner: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="负责人")
    yield_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成品率（汇总）")
    ratio_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="装配放量比")
    cycle_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单件装配周期（天）")
    urgent_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="加急单件周期（天）")
    required_flags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="特征参数适用标记")
    subpart_mode: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="分部件模式（前置/平行/空）")
    subpart_cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="分部件装配周期（天）")
    ramp_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="爬坡时间（天）")
    bottleneck_op: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="瓶颈工序（取小结果）")
    bottleneck_flux: Mapped[float | None] = mapped_column(Float, nullable=True, comment="瓶颈通量")
    water_note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="水汽要求说明")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", comment="状态")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class ProcessRoute(SyncBase):
    """工艺路线（工艺代号×工序序号 唯一，共 ~133 行）。"""

    __tablename__ = "process_routes"
    __table_args__ = (UniqueConstraint("code", "seq", name="uq_route_code_seq"),)

    code: Mapped[str] = mapped_column(String(50), comment="工艺代号")
    seq: Mapped[int] = mapped_column(Integer, comment="工序序号")
    step_raw: Mapped[str] = mapped_column(String(50), comment="工序原文名")
    step_std: Mapped[str] = mapped_column(String(50), comment="规范工序名")
    level: Mapped[str] = mapped_column(String(20), comment="适用级别")
    cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工序装配周期（天）")
    yield_inspect: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次检验合格率")
    yield_overall: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合成品率")
    feature: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="核算特征（如 植球-球数N_b）")
    cf_field: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="折算系数来源（DB胶水/WB引线//）")
    cf_trigger: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="触发条件")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class Order(SyncBase):
    """工单（产品需求）：基础字段 + 优先级引擎字段 + 核算结果回写字段。"""

    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(50), unique=True, comment="订单号")
    product: Mapped[str] = mapped_column(String(100), comment="产品型号")
    code: Mapped[str] = mapped_column(String(50), comment="工艺代号")
    order_type: Mapped[str] = mapped_column(String(10), default="常规", comment="订单类型（常规/加急）")
    first_flag: Mapped[str] = mapped_column(String(20), default="否", comment="首单/复线/变更首件/否")
    water_vapor: Mapped[str] = mapped_column(String(10), default="无", comment="水汽含量要求（有/无）")
    qty: Mapped[int] = mapped_column(Integer, comment="计划批量（只）")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="订单需求日期")
    kit_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="物料齐套时间")
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排产优先级（越小越优先，0=置顶）")
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="BOM 特征（13+2 项）")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="正常", comment="状态（正常/暂停/取消/完成）")

    prio_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="优先级级别（P0~P3）")
    prio_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="6 因子评分")
    prio_source: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="来源（auto/manual/pin）")
    prio_manual: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="手工指定优先级")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶")
    pinned_until: Mapped[date | None] = mapped_column(Date, nullable=True, comment="置顶失效日期")
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="置顶时间")
    pinned_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="置顶操作人")
    sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="拖拽排序序号")
    prio_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="优先级更新时间")
    prio_updated_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="优先级更新人")

    input_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="投料量（核算结果）")
    yield_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, comment="装配放量比（核算结果）")
    y_full: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成品率链乘积（核算结果）")
    cycle_single: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单件周期-采用值（核算结果）")
    cycle_batch: Mapped[float | None] = mapped_column(Float, nullable=True, comment="批量总装配周期（核算结果）")
    adopted_flux: Mapped[float | None] = mapped_column(Float, nullable=True, comment="采用通量（核算结果）")
    bottleneck_op: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="瓶颈工序（核算结果）")
    ramp_applied: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="实际计入爬坡（天）")
    delivery_cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="交付周期（核算结果）")
    latest_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="最晚投料日（核算结果）")
    plan_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产开始日")
    plan_finish_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产完成日")
    gap_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="交期余量（天）")
    judge: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="交付判定（满足/零裕量/延期/无交期）")
    strategy_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="采用策略")


class OrderOperation(SyncBase):
    """工序级需求：产品工单按路线自动分解；支持手工追加（返工/试制插入工序）。"""

    __tablename__ = "order_operations"

    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    seq: Mapped[int] = mapped_column(Integer, comment="工序序号")
    level: Mapped[str] = mapped_column(String(20), comment="级别")
    op: Mapped[str] = mapped_column(String(50), comment="规范工序名")
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="生产模式（排产时按批量分流判定）")
    qty: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工序级数量")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="数量单位")
    feature_key: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="特征参数键（如 N_die）")
    feature_usage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单只特征用量（负荷计算用）")
    source: Mapped[str] = mapped_column(String(10), default="auto", comment="来源（auto=路线分解/manual=手工追加）")
    depends_on_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="前道工序需求 ID（工序间约束）")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注（返工/试制原因等）")


class SystemParam(SyncBase):
    """系统参数（可配置；种子只补缺失、不覆盖用户已改值）。"""

    __tablename__ = "system_params"

    key: Mapped[str] = mapped_column(String(100), unique=True, comment="参数键")
    value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="参数值（字符串/JSON）")
    label: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="显示名")
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="分组")
    hint: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="说明")


class ScheduleBatch(SyncBase):
    """排产批次（一次求解的头部记录）。"""

    __tablename__ = "schedule_batches"

    batch_no: Mapped[str] = mapped_column(String(50), unique=True, comment="批次号")
    base_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产基准日期")
    solver_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="GA/cp_sat/deterministic")
    strategy_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="策略 ID")
    params_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="参数快照")
    kpi: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="KPI 汇总")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="完成", comment="状态")


class ScheduleAllocation(SyncBase):
    """排产分配明细（工序级需求 × 资源 × 日期 × 数量）。"""

    __tablename__ = "schedule_allocations"

    batch_id: Mapped[str] = mapped_column(String(36), comment="排产批次 ID")
    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="工序级需求 ID")
    resource_key: Mapped[str] = mapped_column(String(100), comment="资源（级别|工序|模式）")
    work_date: Mapped[date] = mapped_column(Date, comment="分配日期")
    qty: Mapped[float] = mapped_column(Float, comment="分配数量")


class PriorityLog(SyncBase):
    """优先级变更审计日志（移植 mps-web priority_log 口径）。"""

    __tablename__ = "priority_logs"

    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    order_no: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="订单号（冗余）")
    action: Mapped[str] = mapped_column(String(20), comment="动作（recompute/pin/unpin/reorder）")
    old_priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="原优先级")
    new_priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="新优先级")
    old_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="原级别")
    new_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="新级别")
    old_sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="原拖拽序")
    new_sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="新拖拽序")
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="原因")
    operator: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作人")
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="批量操作批次 ID")
    undo_of: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="撤销对应的日志 ID")


class PriorityBatch(SyncBase):
    """优先级批量操作快照（撤销用）。"""

    __tablename__ = "priority_batches"

    batch_id: Mapped[str] = mapped_column(String(36), unique=True, comment="批次 ID")
    action: Mapped[str] = mapped_column(String(20), comment="动作")
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="条目数")
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="变更快照")
    operator: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作人")
    undone: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已撤销")


class HapConnection(SyncBase):
    """明道云连接配置（密钥加密存储，API 永不回显）。"""

    __tablename__ = "hap_connections"

    base_url: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="明道云地址")
    app_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="App ID")
    app_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AppKey（加密）")
    sign_enc: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Sign（加密）")


class HapMapping(SyncBase):
    """实体→表单映射。"""

    __tablename__ = "hap_mappings"

    entity: Mapped[str] = mapped_column(String(50), unique=True, comment="业务实体 key（order/process_master/...）")
    ws_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="明道云表单 ID")
    sync_direction: Mapped[str] = mapped_column(String(20), default="pull", comment="同步方向（pull/push/both）")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用")


class HapFieldMapping(SyncBase):
    """字段级映射（本地字段 ↔ 明道云控件）。"""

    __tablename__ = "hap_field_mappings"
    __table_args__ = (UniqueConstraint("entity", "local_field", name="uq_hap_field_mapping"),)

    entity: Mapped[str] = mapped_column(String(50), comment="业务实体 key")
    local_field: Mapped[str] = mapped_column(String(50), comment="本地字段名")
    hap_field_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="明道云控件 ID")
    hap_field_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="明道云字段名")
    field_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="类型（str/int/float/date/option/bool/relation）")
    option_map: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="选项值映射")
    relation: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="关联配置")
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="自动匹配置信度")
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否手工调整过")
```

- [ ] **Step 3.4: 修改 `backend/app/models/__init__.py`**

在 `from .schedule import ScheduleTask` 之后追加（并把新类加入 `__all__`）：

```python
from .mps import (
    ProcessMaster, ProcessSet, ProcessRoute, Order, OrderOperation, SystemParam,
    ScheduleBatch, ScheduleAllocation, PriorityLog, PriorityBatch,
    HapConnection, HapMapping, HapFieldMapping,
)
```

`__all__` 追加：
```python
    "ProcessMaster", "ProcessSet", "ProcessRoute", "Order", "OrderOperation", "SystemParam",
    "ScheduleBatch", "ScheduleAllocation", "PriorityLog", "PriorityBatch",
    "HapConnection", "HapMapping", "HapFieldMapping",
```

- [ ] **Step 3.5: 运行测试确认通过**

```powershell
python -m pytest tests/mps/test_mps_models.py -v
```
Expected: 6 passed。

- [ ] **Step 3.6: 提交**

```bash
git add backend/app/models/mps.py backend/app/models/__init__.py backend/tests/mps/test_mps_models.py
git commit -m "feat(models): MPS 核心 13 表模型"
```

---

### Task 4: Alembic 迁移（PostgreSQL 模式）

**Files:**
- Create: `backend/alembic/versions/<auto>_add_mps_core_tables.py`（由命令生成后填充）

- [ ] **Step 4.1: 记录当前迁移头并生成空迁移**

```powershell
cd backend
alembic heads
```
Expected: 输出单一 head（形如 `b2c3d4e5f6g7 (head)`）。记下该 ID（下文记为 `<OLD_HEAD>`）；若出现多个 head，先停下来报告。

```powershell
alembic revision -m "add mps core tables"
```
Expected: 生成 `alembic/versions/<rev>_add_mps_core_tables.py`，其 `down_revision` 自动指向 `<OLD_HEAD>`。

- [ ] **Step 4.2: 填充迁移内容**

用以下代码替换生成文件的全部内容（保留文件头的 `revision/down_revision` 自动生成值，不要改动这两个变量）：

```python
"""add mps core tables

Revision ID: <保持自动生成>
Revises: <保持自动生成>
Create Date: <保持自动生成>
"""
import sqlalchemy as sa

from alembic import op

revision = "<保持自动生成>"
down_revision = "<保持自动生成>"
branch_labels = None
depends_on = None


def _sync_cols() -> list[sa.Column]:
    """SyncBase 出箱列（与 app/models/base.py 一致）。"""
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hap_row_id", sa.String(64), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="SYNCED"),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _sync_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_hap_row_id", table, ["hap_row_id"])
    op.create_index(f"ix_{table}_sync_status", table, ["sync_status"])


TABLES = [
    "process_masters", "process_sets", "process_routes", "orders", "order_operations",
    "system_params", "schedule_batches", "schedule_allocations",
    "priority_logs", "priority_batches",
    "hap_connections", "hap_mappings", "hap_field_mappings",
]


def upgrade() -> None:
    op.create_table(
        "process_masters",
        *_sync_cols(),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("op", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("cycle", sa.Float(), nullable=False),
        sa.Column("yield_assembly", sa.Float(), nullable=True),
        sa.Column("yield_inspect", sa.Float(), nullable=True),
        sa.Column("yield_overall", sa.Float(), nullable=True),
        sa.Column("cap_station", sa.Float(), nullable=True),
        sa.Column("stations", sa.Integer(), nullable=True),
        sa.Column("flux_base", sa.Float(), nullable=True),
        sa.Column("flux_peak", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("feature", sa.String(50), nullable=True),
        sa.Column("split_rule", sa.String(50), nullable=True),
        sa.Column("split_threshold", sa.Integer(), nullable=True),
        sa.Column("cycle_note", sa.String(100), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.UniqueConstraint("level", "op", "mode", name="uq_process_master"),
    )
    _sync_indexes("process_masters")

    op.create_table(
        "process_sets",
        *_sync_cols(),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("form", sa.String(50), nullable=True),
        sa.Column("arch", sa.String(50), nullable=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("version", sa.String(20), nullable=True),
        sa.Column("route_text", sa.String(200), nullable=True),
        sa.Column("owner", sa.String(50), nullable=True),
        sa.Column("yield_ref", sa.Float(), nullable=True),
        sa.Column("ratio_ref", sa.Float(), nullable=True),
        sa.Column("cycle_ref", sa.Float(), nullable=True),
        sa.Column("urgent_ref", sa.Float(), nullable=True),
        sa.Column("required_flags", sa.JSON(), nullable=True),
        sa.Column("subpart_mode", sa.String(10), nullable=True),
        sa.Column("subpart_cycle", sa.Float(), nullable=True),
        sa.Column("ramp_days", sa.Integer(), nullable=True),
        sa.Column("bottleneck_op", sa.String(50), nullable=True),
        sa.Column("bottleneck_flux", sa.Float(), nullable=True),
        sa.Column("water_note", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
    )
    _sync_indexes("process_sets")

    op.create_table(
        "process_routes",
        *_sync_cols(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_raw", sa.String(50), nullable=False),
        sa.Column("step_std", sa.String(50), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("cycle", sa.Float(), nullable=True),
        sa.Column("yield_inspect", sa.Float(), nullable=True),
        sa.Column("yield_overall", sa.Float(), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("cf_field", sa.String(50), nullable=True),
        sa.Column("cf_trigger", sa.String(100), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.UniqueConstraint("code", "seq", name="uq_route_code_seq"),
    )
    _sync_indexes("process_routes")

    op.create_table(
        "orders",
        *_sync_cols(),
        sa.Column("order_no", sa.String(50), nullable=False, unique=True),
        sa.Column("product", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("first_flag", sa.String(20), nullable=False),
        sa.Column("water_vapor", sa.String(10), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("kit_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("prio_level", sa.String(5), nullable=True),
        sa.Column("prio_score", sa.Float(), nullable=True),
        sa.Column("prio_source", sa.String(10), nullable=True),
        sa.Column("prio_manual", sa.Integer(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("pinned_until", sa.Date(), nullable=True),
        sa.Column("pinned_at", sa.DateTime(), nullable=True),
        sa.Column("pinned_by", sa.String(50), nullable=True),
        sa.Column("sort_no", sa.Float(), nullable=True),
        sa.Column("prio_updated_at", sa.DateTime(), nullable=True),
        sa.Column("prio_updated_by", sa.String(50), nullable=True),
        sa.Column("input_qty", sa.Integer(), nullable=True),
        sa.Column("yield_ratio", sa.Float(), nullable=True),
        sa.Column("y_full", sa.Float(), nullable=True),
        sa.Column("cycle_single", sa.Float(), nullable=True),
        sa.Column("cycle_batch", sa.Float(), nullable=True),
        sa.Column("adopted_flux", sa.Float(), nullable=True),
        sa.Column("bottleneck_op", sa.String(50), nullable=True),
        sa.Column("ramp_applied", sa.Integer(), nullable=True),
        sa.Column("delivery_cycle", sa.Float(), nullable=True),
        sa.Column("latest_start_date", sa.Date(), nullable=True),
        sa.Column("plan_start_date", sa.Date(), nullable=True),
        sa.Column("plan_finish_date", sa.Date(), nullable=True),
        sa.Column("gap_days", sa.Integer(), nullable=True),
        sa.Column("judge", sa.String(20), nullable=True),
        sa.Column("strategy_id", sa.String(50), nullable=True),
    )
    _sync_indexes("orders")

    op.create_table(
        "order_operations",
        *_sync_cols(),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("op", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=True),
        sa.Column("qty", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("feature_key", sa.String(20), nullable=True),
        sa.Column("feature_usage", sa.Float(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("depends_on_id", sa.String(36), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
    )
    _sync_indexes("order_operations")

    op.create_table(
        "system_params",
        *_sync_cols(),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("group_name", sa.String(50), nullable=True),
        sa.Column("hint", sa.String(200), nullable=True),
    )
    _sync_indexes("system_params")

    op.create_table(
        "schedule_batches",
        *_sync_cols(),
        sa.Column("batch_no", sa.String(50), nullable=False, unique=True),
        sa.Column("base_date", sa.Date(), nullable=True),
        sa.Column("solver_mode", sa.String(20), nullable=True),
        sa.Column("strategy_id", sa.String(50), nullable=True),
        sa.Column("params_snapshot", sa.JSON(), nullable=True),
        sa.Column("kpi", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
    )
    _sync_indexes("schedule_batches")

    op.create_table(
        "schedule_allocations",
        *_sync_cols(),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=True),
        sa.Column("resource_key", sa.String(100), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
    )
    _sync_indexes("schedule_allocations")
    op.create_index("ix_schedule_allocations_batch_id", "schedule_allocations", ["batch_id"])

    op.create_table(
        "priority_logs",
        *_sync_cols(),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("order_no", sa.String(50), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("old_priority", sa.Integer(), nullable=True),
        sa.Column("new_priority", sa.Integer(), nullable=True),
        sa.Column("old_level", sa.String(5), nullable=True),
        sa.Column("new_level", sa.String(5), nullable=True),
        sa.Column("old_sort_no", sa.Float(), nullable=True),
        sa.Column("new_sort_no", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("operator", sa.String(50), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("undo_of", sa.String(36), nullable=True),
    )
    _sync_indexes("priority_logs")
    op.create_index("ix_priority_logs_order_id", "priority_logs", ["order_id"])

    op.create_table(
        "priority_batches",
        *_sync_cols(),
        sa.Column("batch_id", sa.String(36), nullable=False, unique=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("operator", sa.String(50), nullable=True),
        sa.Column("undone", sa.Boolean(), nullable=False),
    )
    _sync_indexes("priority_batches")

    op.create_table(
        "hap_connections",
        *_sync_cols(),
        sa.Column("base_url", sa.String(200), nullable=True),
        sa.Column("app_id", sa.String(100), nullable=True),
        sa.Column("app_key_enc", sa.Text(), nullable=True),
        sa.Column("sign_enc", sa.Text(), nullable=True),
    )
    _sync_indexes("hap_connections")

    op.create_table(
        "hap_mappings",
        *_sync_cols(),
        sa.Column("entity", sa.String(50), nullable=False, unique=True),
        sa.Column("ws_id", sa.String(64), nullable=True),
        sa.Column("sync_direction", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    _sync_indexes("hap_mappings")

    op.create_table(
        "hap_field_mappings",
        *_sync_cols(),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("local_field", sa.String(50), nullable=False),
        sa.Column("hap_field_id", sa.String(64), nullable=True),
        sa.Column("hap_field_name", sa.String(100), nullable=True),
        sa.Column("field_type", sa.String(20), nullable=True),
        sa.Column("option_map", sa.JSON(), nullable=True),
        sa.Column("relation", sa.JSON(), nullable=True),
        sa.Column("auto_score", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("entity", "local_field", name="uq_hap_field_mapping"),
    )
    _sync_indexes("hap_field_mappings")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
```

- [ ] **Step 4.3: 验证迁移（SQLite 干跑，避免依赖 PG）**

```powershell
$env:DATABASE_URL="sqlite+aiosqlite:///./data/alembic_check.db"
alembic stamp <OLD_HEAD>     # 把空库标记为"链路已到位"（不执行旧迁移）
alembic upgrade head         # 只执行本次新增迁移
alembic downgrade <OLD_HEAD> # 验证 downgrade 可回滚
alembic upgrade head         # 再升级
Remove-Item ./data/alembic_check.db
Remove-Item Env:DATABASE_URL
```
Expected: 三条 alembic 命令均无报错；`upgrade head` 后 `alembic current` 显示 `<newrev> (head)`。（若 data 目录不存在，先 `New-Item -ItemType Directory data -Force`。）

- [ ] **Step 4.4: 提交**

```bash
git add backend/alembic/versions/
git commit -m "feat(db): MPS 核心 13 表 Alembic 迁移"
```

---

### Task 5: 启动适配（SQLite 自动建表、Redis 降级）

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/.env.example`

- [ ] **Step 5.1: 修改 `backend/app/main.py` lifespan**

导入区追加：
```python
from app.core.config import settings
from app.database import init_schema, is_sqlite
```

在 `lifespan` 函数内，`logger.info("初始化 Redis 连接...")` 之前插入建表步骤：
```python
    # 启动事件：本地 SQLite 模式自动建表（服务器 PG 模式由 Alembic 管理）
    await init_schema()
    logger.info("数据库结构检查完成")
```

将 Redis 初始化块（含 `raise`）替换为：
```python
    logger.info("初始化 Redis 连接...")
    try:
        await init_redis()
        logger.info("Redis 连接初始化完成")
    except Exception as e:
        if is_sqlite(settings.DATABASE_URL):
            logger.warning("Redis 连接失败（本地 SQLite 模式降级运行，不影响启动）: {}", e)
        else:
            logger.error("Redis 连接初始化失败（关键服务，启动中止）: {}", e)
            raise
```

- [ ] **Step 5.2: 更新 `backend/.env.example`**

在 `DATABASE_URL=postgresql+asyncpg://...` 行后追加注释与本地模式示例：
```
# 本地单机模式（SQLite，零运维；注释掉上一行后启用本行）
# DATABASE_URL=sqlite+aiosqlite:///./data/mps.db
```

- [ ] **Step 5.3: 手工验证本地模式启动（无 Redis、无明道云）**

```powershell
$env:DATABASE_URL="sqlite+aiosqlite:///./data/mps.db"
python -m uvicorn app.main:app --port 8010
```
Expected（日志）：
- `数据库结构检查完成`
- `Redis 连接失败（本地 SQLite 模式降级运行，不影响启动）`（警告，不中断）
- 服务监听 8010；`Invoke-RestMethod http://localhost:8010/health` 返回 `status=healthy`。

验证后停止服务（Ctrl+C）；`backend/data/mps.db` 已生成 13 张新表。

- [ ] **Step 5.4: 提交**

```bash
git add backend/app/main.py backend/.env.example
git commit -m "feat(startup): SQLite 自动建表与本地模式 Redis 降级"
```

---

### Task 6: MPS 常量模块（移植 mps-web consts.js）

**Files:**
- Create: `backend/app/mps/__init__.py`（空文件）
- Create: `backend/app/mps/consts.py`
- Create: `backend/tests/mps/test_consts.py`

- [ ] **Step 6.1: 编写失败测试**

创建 `backend/tests/mps/test_consts.py`：
```python
"""MPS 常量：特征字段、路线特征映射、参数定义。"""
from app.mps.consts import FEATURE_FIELDS, FEATURE_MAP, PARAM_DEFS


def test_feature_fields_13():
    keys = [f["key"] for f in FEATURE_FIELDS]
    assert len(keys) == 13
    assert "N_die2" in keys and "Y_wire2" in keys and "N_a" in keys


def test_feature_map_db_wb():
    assert FEATURE_MAP["DB-芯片数N_die"] == ["N_die", "Y_die"]
    assert FEATURE_MAP["DB-芯片数N_die-2"] == ["N_die2", "Y_die2"]
    assert FEATURE_MAP["WB-键合线数N_wire-2"] == ["N_wire2", "Y_wire2"]
    assert FEATURE_MAP["工单产品数量N"] == []


def test_param_defs_unique_and_defaults():
    keys = [p["key"] for p in PARAM_DEFS]
    assert len(keys) == len(set(keys))
    defs = {p["key"]: p for p in PARAM_DEFS}
    assert defs["week_days"]["value"] == "6"
    assert defs["peak_factor"]["value"] == "1.1"
    assert defs["order_buffer_days"]["value"] == "1"
    assert defs["reference_batch"]["value"] == "1000"
    assert defs["round_mode"]["value"] == "exact"
    assert defs["ramp_trigger"]["value"] == "first_flag"
```

- [ ] **Step 6.2: 运行确认失败**

```powershell
python -m pytest tests/mps/test_consts.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mps'`。

- [ ] **Step 6.3: 创建 `backend/app/mps/consts.py`**

（内容为 `D:\MPS\mps-web\src\consts.js` 的 1:1 移植 + 新增 4 个参数；键名必须与测试一致）

```python
"""MPS 业务常量（移植自 mps-web src/consts.js，只读参照，不得改动源文件）。"""

FEATURE_FIELDS: list[dict] = [
    {"key": "N_b", "label": "N_b/单只植球数", "unit": "颗", "group": "芯片级"},
    {"key": "N_fc", "label": "N_fc/单只倒装元件数", "unit": "只", "group": "芯片级"},
    {"key": "N_smt", "label": "N_smt/单只贴装元件数", "unit": "只", "group": "通用"},
    {"key": "N_die", "label": "N_die/单只芯片数", "unit": "只", "group": "通用"},
    {"key": "Y_die", "label": "DB/胶水类型数", "unit": "种", "group": "通用"},
    {"key": "N_wire", "label": "N_wire/单只键合根丝数", "unit": "根", "group": "通用"},
    {"key": "Y_wire", "label": "WB/引线类型数", "unit": "种", "group": "通用"},
    {"key": "N_die2", "label": "N_die-2/第2组芯片数", "unit": "只", "group": "第2组"},
    {"key": "Y_die2", "label": "DB/第2组胶水类型数", "unit": "种", "group": "第2组"},
    {"key": "N_wire2", "label": "N_wire-2/第2组键合根丝数", "unit": "根", "group": "第2组"},
    {"key": "Y_wire2", "label": "WB/第2组引线类型数", "unit": "种", "group": "第2组"},
    {"key": "N_bs", "label": "N_bs/单只钎焊部件数", "unit": "只", "group": "组件级"},
    {"key": "N_a", "label": "N_a/单只电装点数(焊点+螺钉)", "unit": "点", "group": "组件级"},
]

FEATURE_MAP: dict[str, list[str]] = {
    "植球-球数N_b": ["N_b"],
    "FC-倒装元件数N_fc": ["N_fc"],
    "钎焊-部件数N_bs": ["N_bs"],
    "SMT-贴装元件数N_smt": ["N_smt"],
    "DB-芯片数N_die": ["N_die", "Y_die"],
    "DB-芯片数N_die-1": ["N_die", "Y_die"],
    "DB-芯片数N_die-2": ["N_die2", "Y_die2"],
    "WB-键合线数N_wire": ["N_wire", "Y_wire"],
    "WB-键合线数N_wire-1": ["N_wire", "Y_wire"],
    "WB-键合线数N_wire-2": ["N_wire2", "Y_wire2"],
    "电装-（焊点+螺钉）数量N_a": ["N_a"],
    "工单产品数量N": [],
}

# 参数定义（11 项来自 mps-web PARAM_DEFS；后 4 项为本系统新增/疑点开关）
PARAM_DEFS: list[dict] = [
    {"key": "week_days", "value": "6", "label": "周工作天数", "group": "排产", "hint": "周负荷可用产能 = 基准通量 × 周工作天数"},
    {"key": "peak_factor", "value": "1.1", "label": "峰值系数", "group": "排产", "hint": "基准峰值通量 = 基准均值通量 × 峰值系数"},
    {"key": "use_peak", "value": "mean", "label": "通量口径", "group": "排产", "hint": "mean=基准均值通量 / peak=基准峰值通量"},
    {"key": "exclude_braze_yield", "value": "1", "label": "组件级放量比剔除钎焊良率", "group": "成品率", "hint": "1=组件级(C系列)放量比不计入钎焊工序综合成品率"},
    {"key": "cf_db_1", "value": "1", "label": "DB胶水类型数=1 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_db_2", "value": "0.9", "label": "DB胶水类型数=2 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_db_3", "value": "0.8", "label": "DB胶水类型数≥3 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_1", "value": "1", "label": "WB引线类型数=1 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_2", "value": "0.95", "label": "WB引线类型数=2 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_3", "value": "0.9", "label": "WB引线类型数≥3 折算系数", "group": "折算系数", "hint": ""},
    {"key": "vapor_cap_cut", "value": "1", "label": "无水汽时封盖工序周期", "group": "周期", "hint": "封盖类工序基准周期在无水汽含量要求时压缩到该值"},
    {"key": "order_buffer_days", "value": "1", "label": "订单缓冲（天）", "group": "交付", "hint": "交付周期 = 批量周期 + 爬坡 + 订单缓冲；疑点：mps-web 未计入，待业务确认"},
    {"key": "reference_batch", "value": "1000", "label": "参考批量（只）", "group": "分流", "hint": "基准通量的分流判定批量；周负荷按订单实际批量动态分流"},
    {"key": "round_mode", "value": "exact", "label": "批量项取整口径", "group": "交付", "hint": "exact=V1.6也算例不取整 / ceil=向上取整；疑点待业务确认"},
    {"key": "ramp_trigger", "value": "first_flag", "label": "爬坡触发口径", "group": "爬坡", "hint": "first_flag=首单/复线/变更首件触发 / all=所有订单；疑点待业务确认"},
]
```

- [ ] **Step 6.4: 运行确认通过**

```powershell
python -m pytest tests/mps/test_consts.py -v
```
Expected: 3 passed。

- [ ] **Step 6.5: 提交**

```bash
git add backend/app/mps backend/tests/mps/test_consts.py
git commit -m "feat(mps): 特征/映射/参数常量（移植 consts.js）"
```

---

### Task 7: 种子数据转换、加载器与导入脚本

**Files:**
- Create: `backend/tools/convert_mps_seed.py`
- Create: `backend/app/seed/__init__.py`（空文件）
- Create: `backend/app/seed/loader.py`
- Create（脚本生成）: `backend/app/seed/mps_seed.json`、`backend/app/seed/demo_orders.json`
- Create: `backend/tools/load_seed.py`
- Create: `backend/tests/mps/test_seed_loader.py`

- [ ] **Step 7.1: 编写转换脚本并生成种子文件**

创建 `backend/tools/convert_mps_seed.py`：

```python
"""把 mps-web 种子转换为本系统种子文件（只读 D:\\MPS，一次运行，产物入库）。

用法：在 backend 目录执行  python tools/convert_mps_seed.py
产物：app/seed/mps_seed.json、app/seed/demo_orders.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MPS_WEB = Path(r"D:\MPS\mps-web")
OUT = Path(__file__).resolve().parents[1] / "app" / "seed"


def build() -> dict:
    src = json.loads((MPS_WEB / "seed.json").read_text(encoding="utf-8"))

    workcenters = []
    for w in src["workcenters"]:
        for m in w["modes"]:
            workcenters.append({
                "level": w["level"], "op": w["op"], "mode": m["mode"],
                "cycle": m["cycle"], "yield_assembly": m.get("yield_assembly"),
                "yield_inspect": m.get("yield_inspect"), "yield_overall": m.get("yield_overall"),
                "cap_station": m.get("cap_station"), "stations": m.get("stations"),
                "flux_base": m.get("flux_base"), "flux_peak": m.get("flux_peak"),
                "unit": m.get("unit"), "feature": m.get("feature"),
                "split_rule": m.get("split_rule"), "split_threshold": m.get("split_threshold"),
                "cycle_note": None, "remark": m.get("note"),
            })

    processes = [{
        "code": p["code"], "form": p.get("form") or None, "arch": p.get("arch") or None,
        "name": p.get("name"), "feature": p.get("feature"), "version": p.get("version"),
        "route_text": p.get("route_text"), "owner": p.get("owner") or None,
        "yield_ref": p.get("yield_ref"), "ratio_ref": p.get("ratio_ref"),
        "cycle_ref": p.get("cycle_ref"), "urgent_ref": p.get("urgent_ref"),
        "required_flags": p.get("required_flags"),
        "subpart_mode": p.get("subpart_mode") or None, "subpart_cycle": p.get("subpart_cycle") or None,
        "ramp_days": p.get("ramp_days"), "bottleneck_op": None, "bottleneck_flux": None,
        "water_note": p.get("note") or None, "status": "启用", "remark": p.get("note") or None,
    } for p in src["processes"]]

    routes = [{
        "code": r["code"], "seq": r["seq"], "step_raw": r["step_raw"], "step_std": r["step_std"],
        "level": r["level"], "cycle": r.get("cycle"), "yield_inspect": r.get("yield_inspect"),
        "yield_overall": r.get("yield_overall"), "feature": r.get("feature"),
        "cf_field": r.get("cf_field"), "cf_trigger": r.get("cf_trigger"),
        "note": r.get("note") or None,
    } for r in src["routes"]]

    p = src["params"]
    params = {
        "week_days": str(p["week_days"]),
        "peak_factor": str(p["peak_factor"]),
        "exclude_braze_yield": str(p["exclude_braze_yield_for_component"]),
        "cf_db_1": str(p["cf_db_by_glue_count"]["1"]),
        "cf_db_2": str(p["cf_db_by_glue_count"]["2"]),
        "cf_db_3": str(p["cf_db_by_glue_count"]["3"]),
        "cf_wb_1": str(p["cf_wb_by_wire_count"]["1"]),
        "cf_wb_2": str(p["cf_wb_by_wire_count"]["2"]),
        "cf_wb_3": str(p["cf_wb_by_wire_count"]["3"]),
    }
    return {"version": 1, "source": "mps-web seed.json (V1.7)",
            "workcenters": workcenters, "processes": processes, "routes": routes, "params": params}


def main() -> None:
    out = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mps_seed.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    orders = json.loads((MPS_WEB / "sample_orders.json").read_text(encoding="utf-8"))
    demo = [{
        "order_no": o["order_no"], "product": o["product"], "code": o["code"],
        "order_type": o["order_type"], "first_flag": o["first_flag"], "water_vapor": o["water_vapor"],
        "qty": o["qty"], "due_date": o.get("due_date"), "kit_date": o.get("kit_date"),
        "priority": o.get("priority"), "features": o.get("features"), "remark": o.get("remark") or "",
    } for o in orders]
    (OUT / "demo_orders.json").write_text(json.dumps(demo, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"workcenters={len(out['workcenters'])} processes={len(out['processes'])} "
          f"routes={len(out['routes'])} orders={len(demo)}")


if __name__ == "__main__":
    main()
```

运行：
```powershell
python tools/convert_mps_seed.py
```
Expected: `workcenters=28 processes=24 routes=133 orders=20`。

- [ ] **Step 7.2: 编写失败测试**

创建 `backend/tests/mps/test_seed_loader.py`：
```python
"""种子导入：行数、抽查值、幂等性与参数保护。"""
from sqlalchemy import func, select

from app.models.mps import Order, ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.consts import PARAM_DEFS
from app.seed.loader import load_mps_seed


async def test_seed_counts(sqlite_session):
    counts = await load_mps_seed(sqlite_session)
    assert counts["workcenters"] == 28
    assert counts["processes"] == 24
    assert counts["routes"] == 133
    assert counts["params_added"] == len(PARAM_DEFS)
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessMaster))).scalar() == 28
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessSet))).scalar() == 24
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessRoute))).scalar() == 133


async def test_seed_spot_values(sqlite_session):
    await load_mps_seed(sqlite_session)
    wc = (await sqlite_session.execute(
        select(ProcessMaster).where(
            ProcessMaster.level == "模块级", ProcessMaster.op == "DB", ProcessMaster.mode == "自动DB")
    )).scalar_one()
    assert wc.flux_base == 6000 and wc.flux_peak == 6600 and wc.split_threshold == 20

    ps = (await sqlite_session.execute(select(ProcessSet).where(ProcessSet.code == "M02-2D"))).scalar_one()
    assert ps.cycle_ref == 6 and ps.urgent_ref == 4
    assert abs(ps.yield_ref - 0.9507210075) < 1e-9
    assert ps.route_text == "DB1-WB1-调试1-封盖前终检1-封盖2"

    r5 = (await sqlite_session.execute(
        select(ProcessRoute).where(ProcessRoute.code == "M02-2D", ProcessRoute.seq == 5)
    )).scalar_one()
    assert r5.step_std == "封盖" and r5.cycle == 2


async def test_seed_idempotent_and_params_preserved(sqlite_session):
    await load_mps_seed(sqlite_session)
    param = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "week_days"))).scalar_one()
    param.value = "5"
    await sqlite_session.commit()

    await load_mps_seed(sqlite_session)
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessMaster))).scalar() == 28
    param2 = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "week_days"))).scalar_one()
    assert param2.value == "5"


async def test_seed_demo_orders_once(sqlite_session):
    counts = await load_mps_seed(sqlite_session, with_demo_orders=True)
    assert counts["demo_orders"] == 20
    counts2 = await load_mps_seed(sqlite_session, with_demo_orders=True)
    assert counts2["demo_orders"] == 0
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 20


async def test_seed_params_fallback_defaults(sqlite_session):
    """转换后的种子只覆盖部分参数；其余参数按 PARAM_DEFS 默认值落库。"""
    await load_mps_seed(sqlite_session)
    p = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "order_buffer_days"))).scalar_one()
    assert p.value == "1"
    p2 = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "peak_factor"))).scalar_one()
    assert p2.value == "1.1"
```

- [ ] **Step 7.3: 运行确认失败**

```powershell
python -m pytest tests/mps/test_seed_loader.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.seed'`。

- [ ] **Step 7.4: 创建 `backend/app/seed/loader.py`**

```python
"""MPS 种子数据导入器：幂等；系统参数只补缺失、不覆盖用户已改值。"""
import json
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.consts import PARAM_DEFS

SEED_DIR = Path(__file__).resolve().parent


def load_seed_json() -> dict:
    return json.loads((SEED_DIR / "mps_seed.json").read_text(encoding="utf-8"))


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


async def load_mps_seed(session: AsyncSession, with_demo_orders: bool = False) -> dict[str, int]:
    """导入基础数据（工序主数据/成套工艺/工艺路线/系统参数），可选导入演示工单。

    幂等策略：
    - 三张主数据表先清空再插入（来源为 mps-web 固化种子）；
    - 系统参数只新增缺失的 key，不覆盖已存在的值；
    - 演示工单仅在 orders 表为空时导入一次。
    """
    seed = load_seed_json()

    await session.execute(delete(ProcessRoute))
    await session.execute(delete(ProcessMaster))
    await session.execute(delete(ProcessSet))
    session.add_all([ProcessMaster(**w) for w in seed["workcenters"]])
    session.add_all([ProcessSet(**p) for p in seed["processes"]])
    session.add_all([ProcessRoute(**r) for r in seed["routes"]])

    existing_keys = {k for (k,) in (await session.execute(select(SystemParam.key))).all()}
    added_params = 0
    for d in PARAM_DEFS:
        if d["key"] in existing_keys:
            continue
        value = str(seed["params"].get(d["key"], d["value"]))
        session.add(SystemParam(
            key=d["key"], value=value, label=d["label"],
            group_name=d.get("group", ""), hint=d.get("hint", ""),
        ))
        added_params += 1

    demo_count = 0
    if with_demo_orders:
        has_orders = (await session.execute(select(Order.id).limit(1))).first() is not None
        if not has_orders:
            orders = json.loads((SEED_DIR / "demo_orders.json").read_text(encoding="utf-8"))
            session.add_all([
                Order(
                    order_no=o["order_no"], product=o["product"], code=o["code"],
                    order_type=o["order_type"], first_flag=o["first_flag"],
                    water_vapor=o["water_vapor"], qty=o["qty"],
                    due_date=_parse_date(o.get("due_date")), kit_date=_parse_date(o.get("kit_date")),
                    priority=o.get("priority"), features=o.get("features"),
                    remark=o.get("remark") or None,
                ) for o in orders
            ])
            demo_count = len(orders)

    await session.commit()
    return {
        "workcenters": len(seed["workcenters"]),
        "processes": len(seed["processes"]),
        "routes": len(seed["routes"]),
        "params_added": added_params,
        "demo_orders": demo_count,
    }
```

- [ ] **Step 7.5: 创建 `backend/tools/load_seed.py`**

```python
"""导入 MPS 种子数据。

用法（在 backend 目录）：
  python tools/load_seed.py                    # 仅基础数据
  python tools/load_seed.py --with-demo-orders # 附带演示工单（orders 为空时）
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session, init_schema
from app.seed.loader import load_mps_seed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-demo-orders", action="store_true")
    args = parser.parse_args()
    await init_schema()
    async with async_session() as session:
        counts = await load_mps_seed(session, with_demo_orders=args.with_demo_orders)
    print("seed loaded:", counts)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7.6: 运行测试确认通过**

```powershell
python -m pytest tests/mps/test_seed_loader.py -v
```
Expected: 5 passed。

- [ ] **Step 7.7: 提交**

```bash
git add backend/tools/convert_mps_seed.py backend/tools/load_seed.py backend/app/seed backend/tests/mps/test_seed_loader.py
git commit -m "feat(seed): MPS 种子转换、加载器与导入脚本"
```

---

### Task 8: 旧业务数据清理脚本（默认 dry-run）

**Files:**
- Create: `backend/tools/clean_old_business_data.py`
- Create: `backend/tests/mps/test_clean_old_business_data.py`

- [ ] **Step 8.1: 编写失败测试**

（清理核心逻辑放 `backend/app/mps/maintenance.py` 以便测试，脚本只做 CLI 包装。）

创建 `backend/tests/mps/test_clean_old_business_data.py`：
```python
"""旧业务数据清理：dry-run 不删、execute 删除、计数正确。"""
from sqlalchemy import func, select

from app.models.mps import Order
from app.mps.maintenance import clean_tables


async def test_clean_dry_run_keeps_rows(sqlite_session):
    sqlite_session.add(Order(order_no="C-1", product="P", code="M02-2D", qty=1))
    await sqlite_session.commit()
    counts = await clean_tables(sqlite_session, tables=["orders"], execute=False)
    assert counts == {"orders": 1}
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 1


async def test_clean_execute_deletes_rows(sqlite_session):
    sqlite_session.add(Order(order_no="C-2", product="P", code="M02-2D", qty=1))
    await sqlite_session.commit()
    counts = await clean_tables(sqlite_session, tables=["orders"], execute=True)
    assert counts == {"orders": 1}
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 0
```

- [ ] **Step 8.2: 运行确认失败**

```powershell
python -m pytest tests/mps/test_clean_old_business_data.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mps.maintenance'`。

- [ ] **Step 8.3: 创建 `backend/app/mps/maintenance.py`**

```python
"""维护操作：旧业务数据清理（保留表结构，仅删数据；默认 dry-run）。"""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 按外键依赖顺序（子表在前）
OLD_BUSINESS_TABLES = [
    "report_work_orders",
    "schedule_results",
    "process_delivery_plans",
    "process_schedule_orders",
    "demand_plans",
    "material_kittings",
    "process_boms",
    "product_processes",
    "line_process_configs",
    "changeover_matrices",
    "buffer_configs",
    "resource_calendars",
    "material_masters",
    "products",
    "process_info",
    "production_lines",
    "schedule_plans",
]


async def clean_tables(
    session: AsyncSession, tables: list[str] | None = None, execute: bool = False
) -> dict[str, int]:
    """统计（并可选删除）指定表的数据行数。

    Args:
        session: 数据库会话
        tables: 表名列表，默认 OLD_BUSINESS_TABLES
        execute: False=仅统计（dry-run）；True=执行删除
    """
    tables = tables or OLD_BUSINESS_TABLES
    counts: dict[str, int] = {}
    for name in tables:
        table = _table(name)
        count = (await session.execute(select(func.count()).select_from(table))).scalar() or 0
        counts[name] = count
        if execute and count:
            await session.execute(delete(table))
    await session.commit()
    return counts


def _table(name: str):
    from sqlalchemy import Table

    from app.database import Base
    import app.models  # noqa: F401

    table = Base.metadata.tables.get(name)
    if table is None:
        raise ValueError(f"未知表名: {name}")
    return table
```

- [ ] **Step 8.4: 创建 `backend/tools/clean_old_business_data.py`**

```python
"""清理旧业务数据（保留表结构；默认 dry-run）。

用法（在 backend 目录）：
  python tools/clean_old_business_data.py            # 预览各表行数
  python tools/clean_old_business_data.py --execute  # 执行删除
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session
from app.mps.maintenance import clean_tables


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="执行删除（默认仅统计）")
    args = parser.parse_args()
    async with async_session() as session:
        counts = await clean_tables(session, execute=args.execute)
    mode = "已删除" if args.execute else "预览（未删除）"
    for name, count in counts.items():
        print(f"{mode}: {name} = {count}")
    print("合计:", sum(counts.values()))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 8.5: 运行测试确认通过**

```powershell
python -m pytest tests/mps/test_clean_old_business_data.py -v
```
Expected: 2 passed。

- [ ] **Step 8.6: 全量回归 + 提交**

```powershell
python -m pytest tests -v
```
Expected: 既有 `test_simulator.py` 通过 + 新增 mps 测试全部通过（PG 相关跳过）。

```bash
git add backend/app/mps/maintenance.py backend/tools/clean_old_business_data.py backend/tests/mps/test_clean_old_business_data.py
git commit -m "feat(tools): 旧业务数据清理（dry-run 默认）"
```

---

## 完成定义（本计划结束时）

1. `docs/checklists/mps-logic-checklist.md` 已交付（90~120 条，含测试用例命名，用户已过目）；
2. `backend` 在 SQLite 模式下 `python -m uvicorn app.main:app` 可无 Redis、无明道云启动，13 张新表自动创建；
3. 种子导入脚本可重复执行：28 工序行 / 24 成套工艺 / 133 路线 / ≥15 系统参数；
4. `python -m pytest tests -v` 全绿（PG 用例按需跳过；有 TEST_PG_URL 时可全跑）；
5. 旧业务数据可一键 dry-run/清理（不碰表结构）；
6. 每个 Task 均已提交（若启用 git）。

## 后续计划衔接

- 计划 2（核算内核）：开始前先读 `docs/checklists/mps-logic-checklist.md` 的 CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 条目，按条目逐条 TDD 实现并回填状态；
- 计划 3（排产内核）：读 SCHED/PRIO 条目；`order_operations` 分解逻辑、优先级引擎、GA 核心在此落地；
- 计划 4（明道云）：`hap_connections/hap_mappings/hap_field_mappings` 三表的使用者，需新增 `cryptography` 依赖；
- 计划 5/6：前端与集成收尾。

## Self-Review 记录（编制者自查）

- **规格覆盖**：设计规格 §4 数据模型（13 表）→ Task 3；§5 双库 → Task 2/4/5；§10 check-list → Task 1；§6~§9（映射/同步/前端/内核）→ 计划 2~6 衔接表已列；旧数据清理 → Task 8；种子三来源中"内置种子"→ Task 7（Excel 导入、明道云拉取留在计划 4/6，已在总览表中标明）。
- **占位符扫描**：无 TBD/TODO；迁移文件中的 `<保持自动生成>` 是"保留命令生成值"的操作说明，并非遗漏（该文件由 `alembic revision` 生成，人工只需填充函数体）。
- **类型一致性**：`engine_kwargs/is_sqlite`（Task 2 定义 ↔ Task 2 测试/ Task 5 使用）；`load_mps_seed` 返回键 `workcenters/processes/routes/params_added/demo_orders`（Task 7 定义 ↔ 测试断言）；`clean_tables(session, tables, execute)`（Task 8 定义 ↔ 测试/脚本调用）；模型类名与 `__init__.py` 导出一致（Task 3）。
