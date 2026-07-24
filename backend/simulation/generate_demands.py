"""需求生成脚本：清空旧需求，生成N条参数化需求。"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from datetime import date, timedelta

from simulation.common import (
    SIM_START_DATE,
    cleanup_all_schedule_data,
    create_demand_plan,
    get_demand_plans,
    get_products,
)


DAILY_OUTPUT_AVG = 800


def estimate_total_quantity(target_days: int) -> int:
    """估算总需求量 = 目标天数 x 日均产出。"""
    return target_days * DAILY_OUTPUT_AVG


def distribute_quantity(total: int, n: int) -> list[int]:
    """将total随机分配到n条需求。"""
    avg = total / n
    quantities = [int(random.uniform(0.5, 1.5) * avg) for _ in range(n)]
    quantities[-1] = max(1, total - sum(quantities[:-1]))
    return quantities


def generate_due_dates(target_days: int, n: int) -> list[date]:
    """生成n条需求的交期，分布在目标天数后半段。"""
    start = SIM_START_DATE + timedelta(days=int(target_days * 0.5))
    end = SIM_START_DATE + timedelta(days=target_days)
    span = (end - start).days
    dates = [start + timedelta(days=random.randint(0, max(span, 1))) for _ in range(n)]
    dates.sort()
    return dates


def assign_products(n: int, products: list[dict], product_codes: str | None = None) -> list[str]:
    """分配产品。

    Args:
        n: 需求数量
        products: 全量产品列表
        product_codes: 可选，逗号分隔的产品编码（如 "PROD-5G-01,PROD-RF-01"）。
            指定后仅从这些产品中分配（轮询+随机），用于单产品/指定多产品测试。
    """
    if product_codes:
        codes = [c.strip() for c in product_codes.split(",") if c.strip()]
        selected = [p for p in products if p.get("prod_code") in codes]
        if not selected:
            raise ValueError(f"未找到匹配的产品编码: {product_codes}")
        # 单产品场景：所有需求都用同一产品；多产品场景：轮询分配后打乱
        assigned = [selected[i % len(selected)]["id"] for i in range(n)]
        random.shuffle(assigned)
        return assigned

    # 默认：随机分配，确保每种产品都被覆盖
    product_ids = [p["id"] for p in products]
    assigned = []
    for i in range(n):
        if i < len(product_ids):
            assigned.append(product_ids[i])
        else:
            assigned.append(random.choice(product_ids))
    random.shuffle(assigned)
    return assigned


def assign_priorities(n: int) -> list[str]:
    """优先级分配：高20%/中60%/低20%。"""
    priorities = []
    for _ in range(n):
        r = random.random()
        if r < 0.2:
            priorities.append("高")
        elif r < 0.8:
            priorities.append("中")
        else:
            priorities.append("低")
    return priorities


async def main(
    num: int,
    target_days: int,
    output: str,
    seed: int | None = None,
    product_codes: str | None = None,
    fixed_quantity: int | None = None,
) -> None:
    """主入口。

    Args:
        product_codes: 可选，逗号分隔的产品编码，指定后仅从这些产品中分配
        fixed_quantity: 可选，固定每条需求的数量（覆盖按目标天数估算的随机分配）
    """
    if seed is not None:
        random.seed(seed)

    print(f"=== 需求生成: {num}条, 目标{target_days}天 ===")
    if product_codes:
        print(f"  指定产品: {product_codes}")
    if fixed_quantity:
        print(f"  固定数量: {fixed_quantity}/条")

    # 1. 物理清空旧需求和排产数据（避免软删除记录残留）
    print("清空旧需求（物理删除）...")
    old_demands = await get_demand_plans()
    old_count = len(old_demands)
    await cleanup_all_schedule_data()  # 直接物理删除所有需求及关联数据
    print(f"  已物理删除 {old_count} 条旧需求")

    # 2. 获取产品列表
    products = await get_products()
    print(f"可用产品: {len(products)} 个")

    # 3. 计算总需求量（fixed_quantity 优先）
    if fixed_quantity:
        total_qty = fixed_quantity * num
        quantities = [fixed_quantity] * num
        print(f"总需求量: {total_qty} (固定 {fixed_quantity}/条 x {num}条)")
    else:
        total_qty = estimate_total_quantity(target_days)
        quantities = distribute_quantity(total_qty, num)
        print(f"总需求量: {total_qty} (日均{DAILY_OUTPUT_AVG} x {target_days}天)")

    # 4. 分配交期、产品、优先级
    due_dates = generate_due_dates(target_days, num)
    product_ids = assign_products(num, products, product_codes=product_codes)
    priorities = assign_priorities(num)

    # 5. 创建需求
    demands = []
    for i in range(num):
        dp_code = f"SIM-{target_days}D-{i+1:03d}"
        product_name = next((p["prod_name"] for p in products if p["id"] == product_ids[i]), "")
        payload = {
            "dp_code": dp_code,
            "product_id": product_ids[i],
            "quantity": quantities[i],
            "unit": "台",
            "due_date": due_dates[i].isoformat(),
            "priority": priorities[i],
            "status": "待排",
        }
        await create_demand_plan(payload)
        demands.append({
            "dp_code": dp_code,
            "product_id": product_ids[i],
            "product_name": product_name,
            "quantity": quantities[i],
            "due_date": due_dates[i].isoformat(),
            "priority": priorities[i],
        })
        print(f"  {dp_code}: {product_name} x{quantities[i]} due={due_dates[i].isoformat()} [{priorities[i]}]")

    # 6. 输出JSON
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"demands": demands, "total_qty": total_qty, "target_days": target_days}, f, ensure_ascii=False, indent=2)
    print(f"\n需求清单已保存: {output}")
    print(f"总需求量: {sum(quantities)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成仿真需求")
    parser.add_argument("--num", type=int, required=True, help="需求数量")
    parser.add_argument("--target-days", type=int, required=True, help="目标完成天数")
    parser.add_argument("--output", type=str, required=True, help="输出JSON路径")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument(
        "--product-codes",
        type=str,
        default=None,
        help="逗号分隔的产品编码（如 PROD-5G-01,PROD-RF-01），仅从指定产品中分配",
    )
    parser.add_argument(
        "--fixed-quantity",
        type=int,
        default=None,
        help="固定每条需求的数量（覆盖按目标天数估算的随机分配）",
    )
    args = parser.parse_args()
    asyncio.run(main(
        args.num, args.target_days, args.output, args.seed,
        product_codes=args.product_codes,
        fixed_quantity=args.fixed_quantity,
    ))