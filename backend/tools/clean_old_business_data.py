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
