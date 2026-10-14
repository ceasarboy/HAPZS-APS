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
