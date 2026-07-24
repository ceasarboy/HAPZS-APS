"""参数化多日排产仿真主脚本（日清模式 + 数据收集）。

流程（每天循环）：
  排产(21天窗口) → 确认 → 逐条报工(random.uniform(min,max)) → snapshot_day → 日终 → 日清 → 重置同步
日清策略：删除"已失效"排产结果/工序排产单 + "已关闭"报工单，保留"已完成"和"待生产"。
仿真期间不触发HAP同步（DISABLE_HAP_SYNC=1）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import date, timedelta

from simulation.common import (
    SIM_START_DATE,
    SCHEDULE_HORIZON,
    SimDataCollector,
    cleanup_all_schedule_data,
    cleanup_schedule_artifacts,
    cleanup_schedule_results,
    confirm_schedule,
    create_schedule,
    daily_cleanup,
    daily_reset,
    get_demand_plans,
    get_products,
    get_processes,
    get_product_processes,
    get_report_work_orders,
    report_work,
    reset_all_sync_status,
    wait_for_schedule,
)


sys.stdout.reconfigure(line_buffering=True)


async def run_simulation(
    num_demands: int,
    target_days: int,
    sim_days: int,
    min_rate: float,
    max_rate: float,
    demands_json: str | None,
    output: str,
    seed: int | None = None,
    scheduling_mode: str = "capacity",
) -> dict:
    """运行参数化仿真，返回收集器导出的字典。

    Args:
        scheduling_mode: 求解模式 ("capacity" 产能累加 / "time_exclusive" 时间独占)
    """
    if seed is not None:
        random.seed(seed)

    config = {
        "num_demands": num_demands,
        "target_days": target_days,
        "sim_days": sim_days,
        "min_rate": min_rate,
        "max_rate": max_rate,
        "schedule_horizon": SCHEDULE_HORIZON,
        "sim_start_date": SIM_START_DATE.isoformat(),
        "seed": seed,
        "scheduling_mode": scheduling_mode,
    }

    mode_label = "产能累加(日级)" if scheduling_mode == "capacity" else "时间独占(小时级)"
    print("=" * 70)
    print(f"参数化排产仿真 — 日清模式 [{scheduling_mode}] {mode_label}")
    print(f"配置: {num_demands}需求 / 目标{target_days}天 / 仿真{sim_days}天 / 完成率{min_rate:.0%}-{max_rate:.0%}")
    print(f"随机种子: {seed} / 求解模式: {scheduling_mode}")
    print("=" * 70)

    # 仿真开始前，重置所有同步状态（避免HAP同步干扰）
    await reset_all_sync_status()
    print("已重置所有同步状态为SYNCED（仿真期间不触发HAP同步）")

    # V3.2修复：清理上次仿真残留的排产产物（SR/PSO/SchedulePlan/RWO）
    # 避免多 plan_id 数据叠加导致 snapshot_day 读取到"超产"假象
    await cleanup_schedule_artifacts()
    print("已清理上次仿真残留的排产产物（保留需求计划）")

    # 初始化数据收集器
    products = await get_products()
    processes = await get_processes()
    product_processes = await get_product_processes()
    collector = SimDataCollector(products, processes, product_processes)
    print(f"已初始化数据收集器: {len(products)}产品, {len(processes)}工序, {len(product_processes)}产品工序")
    parallel_count = len(collector.parallel_process_ids)
    print(f"  并行工序数: {parallel_count}")

    # 获取初始需求计划（基于completed_qty判断完成）
    demands = await get_demand_plans()
    print(f"\n初始需求计划: {len(demands)} 条")
    total_demand: dict[str, dict] = {}
    for dp in demands:
        qty = dp.get("quantity", 0) or 0
        completed = dp.get("completed_qty", 0) or 0
        print(f"  {dp['dp_code']}: 需求={qty}, 已完成={completed}")
        total_demand[dp["id"]] = {
            "code": dp["dp_code"],
            "total": qty + completed,
            "completed": completed,
        }

    final_day = 0
    completed_all = False

    for day in range(1, sim_days + 1):
        final_day = day
        sim_date = SIM_START_DATE + timedelta(days=day - 1)
        sim_date_str = sim_date.isoformat()

        print(f"\n{'=' * 70}")
        print(f"第 {day} 天 ({sim_date_str})")
        print(f"{'=' * 70}")

        # 1. 检查剩余需求（基于completed_qty判断完成）
        demands = await get_demand_plans()
        active_demands = []
        for dp in demands:
            dp_id = dp["id"]
            raw_qty = total_demand.get(dp_id, {}).get("total", dp.get("quantity", 0) or 0)
            completed = dp.get("completed_qty", 0) or 0
            remaining = raw_qty - completed
            if remaining > 0:
                active_demands.append(dp)
        if not active_demands:
            print("所有需求已完成，仿真结束！")
            completed_all = True
            break

        print(f"剩余有需求的计划: {len(active_demands)} 条")
        for dp in active_demands:
            qty = dp.get("quantity", 0) or 0
            comp = dp.get("completed_qty", 0) or 0
            raw = total_demand.get(dp["id"], {}).get("total", qty + comp)
            print(f"  {dp['dp_code']}: 总量={raw}, 已完成={comp}, 剩余={qty}")

        # 1.5 清理旧排产结果（SR/RWO），避免多天排产结果叠加
        # 保留 PSO 因为 pso_completed_qty 记录了历史报工数据
        await cleanup_schedule_results()

        # 2. 排产（25天窗口，scheduling_mode 决定求解模式）
        schedule_end = sim_date + timedelta(days=SCHEDULE_HORIZON)
        print(f"\n步骤1: 排产 ({sim_date_str} ~ {schedule_end.isoformat()}) [{scheduling_mode}]")
        task_id = await create_schedule(sim_date_str, schedule_end.isoformat(), scheduling_mode=scheduling_mode)
        print(f"  排产任务: {task_id[:8]}")

        status = await wait_for_schedule(task_id)
        if status.get("status") != "SUCCESS":
            print(f"  排产失败: {status.get('status')}")
            summary = status.get("result_summary", {})
            if not summary or summary.get("task_count", 0) == 0:
                print("  无排产结果，尝试下一天")
                continue

        summary = status.get("result_summary", {})
        task_count = summary.get("task_count", 0)
        solve_time = summary.get("solve_time_seconds", 0)
        print(f"  排产完成: {task_count} 条结果, 耗时 {solve_time:.2f}s")

        if task_count == 0:
            print("  无排产结果，跳过")
            continue

        # 3. 确认排产
        print(f"\n步骤2: 确认排产")
        confirm_result = await confirm_schedule(task_id)
        print(f"  确认: {confirm_result.get('confirmed', 0)}条, 报工单={confirm_result.get('report_orders', 0)}")

        # 4. 报工（random.uniform完成率）
        print(f"\n步骤3: 报工 (完成率 {min_rate:.0%}-{max_rate:.0%} 随机)")
        rwo_list = await get_report_work_orders()
        pending_rwos = [rwo for rwo in rwo_list if rwo.get("rw_status") == "待报工"]
        print(f"  待报工单: {len(pending_rwos)} 条")

        total_reported = 0
        reported_details = []
        day_rates = []
        for rwo in pending_rwos:
            plan_qty = rwo.get("rw_plan_qty", 0) or 0
            rate = random.uniform(min_rate, max_rate)
            actual_qty = int(round(plan_qty * rate))
            actual_qty = max(1, min(actual_qty, plan_qty))
            day_rates.append(rate)

            dispatch_id = rwo.get("dispatch_id", "")
            try:
                await report_work(dispatch_id, actual_qty)
                total_reported += actual_qty
                reported_details.append({
                    "dispatch_id": dispatch_id,
                    "plan": plan_qty,
                    "actual": actual_qty,
                    "rate": rate,
                })
            except Exception as e:
                print(f"    报工失败: {dispatch_id[:8]}: {e}")

        for d in reported_details[:5]:
            print(f"    派工{d['dispatch_id'][:8]}: 计划={d['plan']}, 实际={d['actual']} ({d['rate']:.1%})")
        if len(reported_details) > 5:
            print(f"    ... 共 {len(reported_details)} 条")
        if day_rates:
            avg_rate = sum(day_rates) / len(day_rates)
            print(f"  总报工数量: {total_reported}, 平均完成率: {avg_rate:.1%}")

        # 5. 验证数据一致性（基于completed_qty计算真实剩余）
        print(f"\n步骤4: 验证数据一致性")
        demands = await get_demand_plans()
        for dp in demands:
            dp_id = dp["id"]
            if dp_id in total_demand:
                raw_qty = total_demand[dp_id]["total"]
                completed = dp.get("completed_qty", 0) or 0
                total_demand[dp_id]["completed"] = completed
                if completed > raw_qty:
                    print(f"  [WARN] {dp['dp_code']}: completed({completed}) > total({raw_qty})")

        for dp in demands:
            dp_id = dp["id"]
            if dp_id in total_demand:
                raw_qty = total_demand[dp_id]["total"]
                completed = dp.get("completed_qty", 0) or 0
                true_remaining = max(raw_qty - completed, 0)
                pct = (completed / raw_qty * 100) if raw_qty > 0 else 0
                print(f"  {dp['dp_code']}: {completed}/{raw_qty} ({pct:.1f}%), 剩余={true_remaining}")

        # 6. 快照当天数据（关键：日清前调用）
        print(f"\n步骤5: 快照当天数据")
        await collector.snapshot_day(sim_date_str)
        print(f"  已快照: {len(collector.dates)} 天数据")

        # 7. 日终处理
        print(f"\n步骤6: 日终处理")
        reset_result = await daily_reset(sim_date_str)
        print(f"  失效={reset_result.get('expired_count', 0)}, 关闭={reset_result.get('closed_report_count', 0)}")

        # 8. 日清：删除失效数据
        print(f"\n步骤7: 日清（删除失效数据）")
        cleanup_result = await daily_cleanup()
        print(f"  删除: 失效排产={cleanup_result['expired_sr']}, 关闭报工={cleanup_result['closed_rwo']}, 失效工序单={cleanup_result['expired_pso']}")

        # 重置同步状态（防止积压）
        await reset_all_sync_status()

        await asyncio.sleep(1)

    # 最终统计
    print(f"\n{'=' * 70}")
    print(f"仿真结束，共运行 {final_day} 天{'（全部完成）' if completed_all else '（达到上限）'}")
    print(f"{'=' * 70}")
    demands = await get_demand_plans()
    all_done = True
    for dp in demands:
        dp_id = dp["id"]
        if dp_id in total_demand:
            raw_qty = total_demand[dp_id]["total"]
            completed = dp.get("completed_qty", 0) or 0
            remaining = raw_qty - completed
            pct = (completed / raw_qty * 100) if raw_qty > 0 else 0
            icon = "OK" if remaining <= 0 else "  "
            if remaining > 0:
                all_done = False
            print(f"  [{icon}] {dp['dp_code']}: {completed}/{raw_qty} ({pct:.1f}%), 剩余={remaining}")

    config["final_day"] = final_day
    config["completed_all"] = completed_all and all_done
    config["total_demand_count"] = len(total_demand)

    # 导出数据
    export_data = collector.export_to_dict(config)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n仿真数据已导出: {output}")
    print(f"  日期数: {len(export_data['dates'])}")
    print(f"  甘特图项目数: {len(export_data['gantt_data'])}")

    return export_data


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="参数化排产仿真（日清模式）")
    parser.add_argument("--num-demands", type=int, required=True, help="需求数量")
    parser.add_argument("--target-days", type=int, required=True, help="目标完成天数")
    parser.add_argument("--sim-days", type=int, default=25, help="仿真推演天数（默认25）")
    parser.add_argument("--min-rate", type=float, required=True, help="最低完成率（如0.85）")
    parser.add_argument("--max-rate", type=float, required=True, help="最高完成率（如0.95）")
    parser.add_argument("--demands-json", type=str, default=None, help="预生成需求JSON路径（可选，跳过需求生成）")
    parser.add_argument("--output", type=str, required=True, help="仿真数据输出JSON路径")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认42）")
    parser.add_argument(
        "--scheduling-mode",
        type=str,
        default="capacity",
        choices=["capacity", "time_exclusive"],
        help="求解模式: capacity=产能累加(日级), time_exclusive=时间独占(小时级)",
    )
    args = parser.parse_args()

    asyncio.run(run_simulation(
        num_demands=args.num_demands,
        target_days=args.target_days,
        sim_days=args.sim_days,
        min_rate=args.min_rate,
        max_rate=args.max_rate,
        demands_json=args.demands_json,
        output=args.output,
        seed=args.seed,
        scheduling_mode=args.scheduling_mode,
    ))


if __name__ == "__main__":
    main_cli()
