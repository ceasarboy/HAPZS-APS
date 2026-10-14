"""一键执行多轮排产仿真测试。

用法:
  python -m simulation.run_all --test 1          # 旧测试1（capacity模式）
  python -m simulation.run_all --test 2          # 旧测试2（capacity模式）
  python -m simulation.run_all --test A1         # 新测试A1单模式（capacity）
  python -m simulation.run_all --test A1 --mode time_exclusive  # 新测试A1指定模式
  python -m simulation.run_all --test new        # 5个新测试 × capacity 模式
  python -m simulation.run_all --test compare    # 5个新测试 × 2模式 = 10个对比测试
  python -m simulation.run_all --test all        # 旧测试1+2（capacity模式）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# ── 旧测试配置（仅 capacity 模式，保持兼容）──────────────────────────────
LEGACY_TEST_CONFIGS = {
    1: {
        "num": 8,
        "target_days": 20,
        "sim_days": 25,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "title": "测试1：8需求/20天目标/85-95%完成率",
    },
    2: {
        "num": 11,
        "target_days": 14,
        "sim_days": 25,
        "min_rate": 0.60,
        "max_rate": 0.90,
        "title": "测试2：11需求/14天目标/60-90%完成率",
    },
}

# ── 新测试配置（A1/A2/B1/B2/B3，每个 × 2 模式）──────────────────────────
NEW_TEST_CONFIGS = {
    "A1": {
        "num": 1,
        "target_days": 10,
        "sim_days": 25,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "product_codes": "PROD-5G-01",
        "fixed_quantity": 800,
        "title": "测试A1：PROD-5G-01 / 1需求 / 800台 / 10天目标",
    },
    "A2": {
        "num": 1,
        "target_days": 7,
        "sim_days": 25,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "product_codes": "PROD-RF-01",
        "fixed_quantity": 500,
        "title": "测试A2：PROD-RF-01 / 1需求 / 500台 / 7天目标",
    },
    "B1": {
        "num": 3,
        "target_days": 14,
        "sim_days": 30,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "title": "测试B1：3需求 / 14天目标 / 30天仿真（小批量）",
    },
    "B2": {
        "num": 8,
        "target_days": 20,
        "sim_days": 35,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "title": "测试B2：8需求 / 20天目标 / 35天仿真（中批量）",
    },
    "B3": {
        "num": 15,
        "target_days": 25,
        "sim_days": 40,
        "min_rate": 0.85,
        "max_rate": 0.95,
        "title": "测试B3：15需求 / 25天目标 / 40天仿真（大批量，部分可能未完成）",
    },
}

SCHEDULING_MODES = ["capacity", "time_exclusive"]

OUTPUT_DIR = Path(__file__).parent / "output"
BACKEND_DIR = Path(__file__).parent.parent


def _run_legacy_test(test_id: int, seed: int = 42) -> bool:
    """执行旧测试（仅 capacity 模式）。"""
    cfg = LEGACY_TEST_CONFIGS[test_id]
    print("\n" + "#" * 70)
    print(f"# 执行旧测试 {test_id}: {cfg['title']}")
    print("#" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    demands_json = str(OUTPUT_DIR / f"test{test_id}_demands.json")
    sim_json = str(OUTPUT_DIR / f"test{test_id}_sim.json")
    report_html = str(OUTPUT_DIR / f"test{test_id}_report.html")

    # 步骤1: 生成需求
    print(f"\n[1/3] 生成需求: {cfg['num']}条, 目标{cfg['target_days']}天")
    cmd = [
        sys.executable, "-m", "simulation.generate_demands",
        "--num", str(cfg["num"]),
        "--target-days", str(cfg["target_days"]),
        "--output", demands_json,
        "--seed", str(seed),
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"需求生成失败 (exit {result.returncode})")
        return False

    # 步骤2: 运行仿真（capacity 模式）
    print(f"\n[2/3] 运行仿真: {cfg['sim_days']}天, 完成率{cfg['min_rate']:.0%}-{cfg['max_rate']:.0%}")
    cmd = [
        sys.executable, "-m", "simulation.run_simulation",
        "--num-demands", str(cfg["num"]),
        "--target-days", str(cfg["target_days"]),
        "--sim-days", str(cfg["sim_days"]),
        "--min-rate", str(cfg["min_rate"]),
        "--max-rate", str(cfg["max_rate"]),
        "--demands-json", demands_json,
        "--output", sim_json,
        "--seed", str(seed),
        "--scheduling-mode", "capacity",
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"仿真失败 (exit {result.returncode})")
        return False

    # 步骤3: 生成报告
    print(f"\n[3/3] 生成HTML报告")
    cmd = [
        sys.executable, "-m", "simulation.generate_report",
        "--input", sim_json,
        "--output", report_html,
        "--title", cfg["title"],
        "--scheduling-mode", "capacity",
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"报告生成失败 (exit {result.returncode})")
        return False

    print(f"\n测试 {test_id} 完成！")
    print(f"  需求清单: {demands_json}")
    print(f"  仿真数据: {sim_json}")
    print(f"  HTML报告: {report_html}")
    return True


def run_test(test_id: str, scheduling_mode: str, seed: int = 42) -> bool:
    """执行新测试：生成需求 → 运行仿真 → 生成报告（指定模式）。

    Args:
        test_id: 测试编号（A1/A2/B1/B2/B3）
        scheduling_mode: 求解模式（capacity / time_exclusive）
        seed: 随机种子
    """
    cfg = NEW_TEST_CONFIGS[test_id]
    print("\n" + "#" * 70)
    print(f"# 执行测试 {test_id} [{scheduling_mode}]: {cfg['title']}")
    print("#" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 文件名包含模式后缀，避免覆盖
    demands_json = str(OUTPUT_DIR / f"test{test_id}_{scheduling_mode}_demands.json")
    sim_json = str(OUTPUT_DIR / f"test{test_id}_{scheduling_mode}_sim.json")
    report_html = str(OUTPUT_DIR / f"test{test_id}_{scheduling_mode}_report.html")

    # 步骤1: 生成需求（每次都重新生成，确保 DB 状态干净）
    # 注意：每次测试都必须调用 generate_demands，因为它内部会调用
    # cleanup_all_schedule_data() 清空旧需求和排产数据，避免上次测试的
    # completed_qty 残留导致本次测试读取到错误的总需求量。
    print(f"\n[1/3] 生成需求: {cfg['num']}条, 目标{cfg['target_days']}天")
    cmd = [
        sys.executable, "-m", "simulation.generate_demands",
        "--num", str(cfg["num"]),
        "--target-days", str(cfg["target_days"]),
        "--output", demands_json,
        "--seed", str(seed),
    ]
    if cfg.get("product_codes"):
        cmd.extend(["--product-codes", cfg["product_codes"]])
    if cfg.get("fixed_quantity"):
        cmd.extend(["--fixed-quantity", str(cfg["fixed_quantity"])])
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"需求生成失败 (exit {result.returncode})")
        return False

    # 步骤2: 运行仿真（指定模式）
    mode_label = "产能累加(日级)" if scheduling_mode == "capacity" else "时间独占(小时级)"
    print(f"\n[2/3] 运行仿真 [{scheduling_mode}] {mode_label}: {cfg['sim_days']}天, 完成率{cfg['min_rate']:.0%}-{cfg['max_rate']:.0%}")
    cmd = [
        sys.executable, "-m", "simulation.run_simulation",
        "--num-demands", str(cfg["num"]),
        "--target-days", str(cfg["target_days"]),
        "--sim-days", str(cfg["sim_days"]),
        "--min-rate", str(cfg["min_rate"]),
        "--max-rate", str(cfg["max_rate"]),
        "--demands-json", demands_json,
        "--output", sim_json,
        "--seed", str(seed),
        "--scheduling-mode", scheduling_mode,
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"仿真失败 (exit {result.returncode})")
        return False

    # 步骤3: 生成报告
    print(f"\n[3/3] 生成HTML报告 [{scheduling_mode}]")
    title = f"{cfg['title']} [{scheduling_mode}]"
    cmd = [
        sys.executable, "-m", "simulation.generate_report",
        "--input", sim_json,
        "--output", report_html,
        "--title", title,
        "--scheduling-mode", scheduling_mode,
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        print(f"报告生成失败 (exit {result.returncode})")
        return False

    print(f"\n测试 {test_id} [{scheduling_mode}] 完成！")
    print(f"  需求清单: {demands_json}")
    print(f"  仿真数据: {sim_json}")
    print(f"  HTML报告: {report_html}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行多轮排产仿真测试")
    parser.add_argument(
        "--test",
        type=str,
        required=True,
        choices=["1", "2", "A1", "A2", "B1", "B2", "B3", "new", "all", "compare"],
        help="测试编号(1/2=旧测试; A1/A2/B1/B2/B3=新测试单模式; new=5新测试×capacity; all=旧1+2; compare=5新测试×2模式)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="capacity",
        choices=["capacity", "time_exclusive"],
        help="求解模式（仅对 A1/A2/B1/B2/B3 单测试生效，默认 capacity）",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认42）")
    args = parser.parse_args()

    if args.test in ("1", "2"):
        _run_legacy_test(int(args.test), args.seed)
    elif args.test == "all":
        # 旧测试 1 + 2（仅 capacity）
        results = {tid: _run_legacy_test(tid, args.seed) for tid in [1, 2]}
        _print_summary({f"测试{tid}": ok for tid, ok in results.items()})
    elif args.test in ("A1", "A2", "B1", "B2", "B3"):
        # 单个新测试，指定模式
        ok = run_test(args.test, args.mode, args.seed)
        _print_summary({f"测试{args.test}[{args.mode}]": ok})
    elif args.test == "new":
        # 5 个新测试 × capacity 模式
        results = {}
        for tid in ["A1", "A2", "B1", "B2", "B3"]:
            ok = run_test(tid, "capacity", args.seed)
            results[f"测试{tid}[capacity]"] = ok
        _print_summary(results)
    elif args.test == "compare":
        # 5 个新测试 × 2 模式 = 10 个对比测试
        results = {}
        for tid in ["A1", "A2", "B1", "B2", "B3"]:
            for mode in SCHEDULING_MODES:
                ok = run_test(tid, mode, args.seed)
                results[f"测试{tid}[{mode}]"] = ok
        _print_summary(results)


def _print_summary(results: dict[str, bool]) -> None:
    print("\n" + "#" * 70)
    print("# 测试结果汇总")
    print("#" * 70)
    for key, ok in results.items():
        status = "成功" if ok else "失败"
        print(f"  {key}: {status}")
    success = sum(1 for ok in results.values() if ok)
    print(f"\n共 {len(results)} 个测试, 成功 {success} 个")


if __name__ == "__main__":
    main()