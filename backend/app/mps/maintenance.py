"""维护操作：旧业务数据清理（保留表结构，仅删数据；默认 dry-run）。"""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 按外键依赖顺序（子表在前，父表在后）
OLD_BUSINESS_TABLES = [
    "report_work_orders",
    "schedule_results",
    "process_delivery_plans",
    "process_schedule_orders",
    "material_kittings",
    "demand_plans",
    "process_boms",
    "product_processes",
    "changeover_matrices",
    "line_process_configs",
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

    注意：破坏性工具——execute=True 时删除表中全部数据；
    tables 可传 metadata 中任意表名，调用方自行保证表名可信
    （生产入口 CLI 固定使用 OLD_BUSINESS_TABLES，不暴露表名参数）。

    Args:
        session: 数据库会话
        tables: 表名列表；None=OLD_BUSINESS_TABLES；[]=不做任何事
        execute: False=仅统计（dry-run）；True=执行删除
    """
    tables = tables if tables is not None else OLD_BUSINESS_TABLES
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
    from app.database import Base
    import app.models  # noqa: F401

    table = Base.metadata.tables.get(name)
    if table is None:
        raise ValueError(f"未知表名: {name}")
    return table
