"""调试HAP工作表结构"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
from app.hap.client import HAPClient

async def main():
    client = HAPClient()
    
    # 工序信息表
    ws_id = "6a2ded6888359ed358a4facd"
    structure = await client.get_worksheet_structure(ws_id)
    print("=== 工序信息表结构 ===")
    print(json.dumps(structure, indent=2, ensure_ascii=False, default=str)[:3000])
    
    # 产品工艺表
    ws_id2 = "6a2ded6d3005b538f6a54ef1"
    structure2 = await client.get_worksheet_structure(ws_id2)
    print("\n=== 产品工艺表结构 ===")
    print(json.dumps(structure2, indent=2, ensure_ascii=False, default=str)[:3000])

if __name__ == "__main__":
    asyncio.run(main())
