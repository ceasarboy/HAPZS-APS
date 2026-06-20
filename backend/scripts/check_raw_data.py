"""查看HAP原始返回数据"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
from app.hap.client import HAPClient

async def main():
    client = HAPClient()
    
    # 查看工序信息原始数据
    print("=== 工序信息原始数据 ===")
    rows = await client.get_rows("6a2ded6888359ed358a4facd", page_size=2)
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    
    # 查看产品工艺原始数据
    print("\n=== 产品工艺原始数据 ===")
    rows = await client.get_rows("6a2ded6d3005b538f6a54ef1", page_size=2)
    print(json.dumps(rows, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
