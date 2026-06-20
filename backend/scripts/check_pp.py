import asyncio
from app.services.schedule_service import ScheduleService

async def check():
    svc = ScheduleService()
    data = await svc.fetch_scheduling_data()
    pp = data.product_processes
    print(f"Product processes: {len(pp)}")
    for p in pp[:5]:
        pid = p.product_id[:8] if p.product_id else "EMPTY"
        prid = p.process_id[:8] if p.process_id else "EMPTY"
        print(f"  product_id={pid} process_id={prid} seq={p.seq}")
    dp = data.demand_plans
    print(f"Demand plans: {len(dp)}")
    for d in dp[:3]:
        pid = d.product_id[:8] if d.product_id else "EMPTY"
        print(f"  product_id={pid} dp_code={d.dp_code}")

asyncio.run(check())
