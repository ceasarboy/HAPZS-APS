"""清理旧业务数据（保留表结构；默认 dry-run）。

前置提示：建议先备份（pg_dump），再 dry-run 复核计数，然后停服执行 --execute。

用法（在 backend 目录）：
  python tools/clean_old_business_data.py            # 预览各表行数
  python tools/clean_old_business_data.py --execute  # 执行删除
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.database import async_session, init_schema
from app.mps.maintenance import clean_tables


async def main() -> None:
    parser = argparse.ArgumentParser(description="清理旧业务数据（保留表结构，默认 dry-run）")
    parser.add_argument("--execute", action="store_true", help="执行删除（默认仅统计）")
    args = parser.parse_args()
    db_display = make_url(settings.DATABASE_URL).render_as_string(hide_password=True)
    print(f"目标数据库: {db_display}")
    print(f"模式: {'执行删除' if args.execute else '预览（未删除）'}")
    await init_schema()  # 本地 SQLite 首次运行时自动建表（PG 由 Alembic 管理）
    async with async_session() as session:
        counts = await clean_tables(session, execute=args.execute)
    for name, count in counts.items():
        print(f"  {name} = {count}")
    print("合计:", sum(counts.values()))


if __name__ == "__main__":
    asyncio.run(main())
