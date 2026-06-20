"""调试HAP行数据格式"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
from app.hap.client import HAPClient

async def main():
    client = HAPClient()
    
    # 查看产品表行数据
    print("=== 产品表行数据 ===")
    rows = await client.get_rows("6a2bf816c839766934ee62e8", page_size=2)
    for row in rows.get("data", {}).get("rows", [])[:2]:
        print(json.dumps(row, indent=2, ensure_ascii=False, default=str)[:1000])
        print("---")
    
    # 查看工序表行数据
    print("\n=== 工序表行数据 ===")
    rows = await client.get_rows("6a2ded6888359ed358a4facd", page_size=2)
    for row in rows.get("data", {}).get("rows", [])[:2]:
        print(json.dumps(row, indent=2, ensure_ascii=False, default=str)[:1000])
        print("---")

if __name__ == "__main__":
    asyncio.run(main())
