"""MPS 种子数据导入器：幂等；系统参数只补缺失、不覆盖用户已改值。

注意：
- 重跑会重置三张主数据表（删后重插），含 id/hap_row_id/sync_status 等出箱字段；
  明道云同步启用后（计划4）重跑会切断同步关联，届时需改为差异化 upsert 或先禁用同步。
- 修改 PARAM_DEFS 中"已存在键"的默认值对既有库不生效（只补缺失），
  需配套数据迁移或显式重置手段（计划2开工前定规则）。
- 本函数会 commit 传入的会话（调用方不必再提交）。
"""
import json
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.consts import PARAM_DEFS

SEED_DIR = Path(__file__).resolve().parent


def load_seed_json() -> dict:
    return json.loads((SEED_DIR / "mps_seed.json").read_text(encoding="utf-8"))


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


async def load_mps_seed(session: AsyncSession, with_demo_orders: bool = False) -> dict[str, int]:
    """导入基础数据（工序主数据/成套工艺/工艺路线/系统参数），可选导入演示工单。

    幂等策略：
    - 三张主数据表先清空再插入（来源为 mps-web 固化种子）；
    - 系统参数只新增缺失的 key，不覆盖已存在的值；
    - 演示工单仅在 orders 表为空时导入一次。
    """
    seed = load_seed_json()

    await session.execute(delete(ProcessRoute))
    await session.execute(delete(ProcessMaster))
    await session.execute(delete(ProcessSet))
    session.add_all([ProcessMaster(**w) for w in seed["workcenters"]])
    session.add_all([ProcessSet(**p) for p in seed["processes"]])
    session.add_all([ProcessRoute(**r) for r in seed["routes"]])

    existing_keys = {k for (k,) in (await session.execute(select(SystemParam.key))).all()}
    added_params = 0
    for d in PARAM_DEFS:
        if d["key"] in existing_keys:
            continue
        value = str(seed["params"].get(d["key"], d["value"]))
        session.add(SystemParam(
            key=d["key"], value=value, label=d["label"],
            group_name=d.get("group", ""), hint=d.get("hint", ""),
        ))
        added_params += 1

    demo_count = 0
    if with_demo_orders:
        has_orders = (await session.execute(select(Order.id).limit(1))).first() is not None
        if not has_orders:
            orders = json.loads((SEED_DIR / "demo_orders.json").read_text(encoding="utf-8"))
            session.add_all([
                Order(
                    order_no=o["order_no"], product=o["product"], code=o["code"],
                    order_type=o["order_type"], first_flag=o["first_flag"],
                    water_vapor=o["water_vapor"], qty=o["qty"],
                    due_date=_parse_date(o.get("due_date")), kit_date=_parse_date(o.get("kit_date")),
                    priority=o.get("priority"), features=o.get("features"),
                    remark=o.get("remark") or None,
                ) for o in orders
            ])
            demo_count = len(orders)

    await session.commit()
    return {
        "workcenters": len(seed["workcenters"]),
        "processes": len(seed["processes"]),
        "routes": len(seed["routes"]),
        "params_added": added_params,
        "demo_orders": demo_count,
    }
