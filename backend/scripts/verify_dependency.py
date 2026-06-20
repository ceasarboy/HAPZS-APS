"""验证工序依赖关系数据 - 打印所有字段"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
from app.hap.client import HAPClient

async def main():
    client = HAPClient()
    
    # 验证工序信息
    print("=== 工序信息验证 ===")
    rows = await client.get_rows("6a2ded6888359ed358a4facd", page_size=3)
    for row in rows.get("data", {}).get("rows", [])[:3]:
        print(json.dumps(row.get("fields", {}), indent=2, ensure_ascii=False, default=str))
        print("---")
    
    # 验证产品工艺
    print("\n=== 产品工艺验证 ===")
    rows = await client.get_rows("6a2ded6d3005b538f6a54ef1", page_size=3)
    for row in rows.get("data", {}).get("rows", [])[:3]:
        print(json.dumps(row.get("fields", {}), indent=2, ensure_ascii=False, default=str))
        print("---")

if __name__ == "__main__":
    asyncio.run(main())
