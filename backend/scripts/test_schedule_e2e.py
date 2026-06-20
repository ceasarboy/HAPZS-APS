"""端到端排产验证 - 检查工序依赖关系是否生效"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import httpx
import json

API_BASE = "http://localhost:8000"
API_KEY = "aps-hap-local-2026"

async def main():
    async with httpx.AsyncClient(base_url=API_BASE, headers={"X-API-Key": API_KEY}, timeout=120) as client:
        # 触发排产
        print("=== 触发排产 ===")
        resp = await client.post("/api/v1/schedule/create", json={
            "start_time": "2026-06-20",
            "end_time": "2026-06-27",
            "solver_type": "ortools",
            "freeze_horizon": 0,
        })
        print(f"Status: {resp.status_code}")
        data = resp.json()
        task_id = data.get("task_id", "")
        print(f"Task ID: {task_id}")
        
        # 轮询状态
        print("\n=== 等待排产完成 ===")
        for i in range(60):
            await asyncio.sleep(2)
            resp = await client.get(f"/api/v1/schedule/{task_id}/status")
            data = resp.json()
            status = data.get("status", "")
            print(f"  [{i*2}s] Status: {status}")
            if status in ("SUCCESS", "COMPLETED", "FAILURE", "FAILED"):
                break
        
        # 获取结果
        print("\n=== 获取排产结果 ===")
        resp = await client.get("/api/v1/result/latest")
        data = resp.json()
        items = data.get("items", [])
        print(f"总任务数: {len(items)}")
        
        # 按产品分组统计
        product_stats = {}
        for item in items:
            product = item.get("product", "未知")
            process = item.get("process", "未知")
            priority = item.get("priority", "中")
            key = f"{product}"
            if key not in product_stats:
                product_stats[key] = []
            product_stats[key].append({
                "process": process,
                "priority": priority,
                "timeSlot": item.get("timeSlot", ""),
                "line": item.get("line", ""),
            })
        
        for product, tasks in product_stats.items():
            print(f"\n--- {product} ({len(tasks)} tasks) ---")
            # 按时间排序
            tasks.sort(key=lambda x: x.get("timeSlot", ""))
            for t in tasks[:20]:  # 只显示前20个
                print(f"  {t['timeSlot'][:16]} | {t['line'][:8]} | {t['process'][:10]} | 优先级:{t['priority']}")
            if len(tasks) > 20:
                print(f"  ... 还有 {len(tasks)-20} 个任务")

if __name__ == "__main__":
    asyncio.run(main())
