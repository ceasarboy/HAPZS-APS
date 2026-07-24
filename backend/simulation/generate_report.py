"""HTML报告生成器：读取仿真JSON，生成ECharts可视化报告。

报告结构：
  1. 标题区 + 配置摘要
  2. 每日总览表
  3. 工序曲线图（每日每工序计划 vs 实际）
  4. 汇总柱状图（每日总计划/总实际 + 完成率线）
  5. 每项目甘特图（计划区间 + 实际完成 + 并行工序标记）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta


ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"


def parse_date(s: str) -> datetime:
    """解析YYYY-MM-DD字符串为datetime。"""
    return datetime.strptime(s, "%Y-%m-%d")


def date_offset_days(start: str, days: float) -> str:
    """从start日期偏移days天，返回ISO字符串。"""
    return (parse_date(start) + timedelta(days=days)).strftime("%Y-%m-%d")


def build_overview_table(data: dict) -> str:
    """构建每日总览表HTML。"""
    dates = data.get("dates", [])
    daily_summary = data.get("daily_summary", {})
    rows = []
    for d in dates:
        s = daily_summary.get(d, {})
        plan = s.get("total_plan", 0)
        actual = s.get("total_actual", 0)
        rate = (actual / plan * 100) if plan > 0 else 0
        rate_class = "rate-high" if rate >= 85 else ("rate-mid" if rate >= 60 else "rate-low")
        rows.append(
            f"<tr><td>{d}</td><td>{plan}</td><td>{actual}</td>"
            f'<td class="{rate_class}">{rate:.1f}%</td></tr>'
        )
    return "\n".join(rows)


def build_process_chart_option(data: dict) -> dict:
    """构建工序曲线图ECharts配置。"""
    dates = data.get("dates", [])
    processes = data.get("processes", [])
    daily_process_data = data.get("daily_process_data", {})

    # 为每个工序生成两条线（计划/实际）
    series = []
    for proc in processes:
        pid = proc["id"]
        pname = proc["name"] or pid[:8]
        plan_data = []
        actual_data = []
        for d in dates:
            entry = daily_process_data.get(d, {}).get(pid, {})
            plan_data.append(entry.get("plan", 0))
            actual_data.append(entry.get("actual", 0))
        series.append({
            "name": f"{pname}-计划",
            "type": "line",
            "data": plan_data,
            "smooth": True,
        })
        series.append({
            "name": f"{pname}-实际",
            "type": "line",
            "data": actual_data,
            "smooth": True,
        })

    return {
        "title": {"text": "每日工序计划 vs 实际数量"},
        "tooltip": {"trigger": "axis"},
        "legend": {"type": "scroll", "bottom": 0},
        "grid": {"left": "8%", "right": "5%", "bottom": "15%", "top": "15%"},
        "xAxis": {"type": "category", "data": dates},
        "yAxis": {"type": "value", "name": "数量"},
        "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        "series": series,
    }


def build_summary_chart_option(data: dict) -> dict:
    """构建汇总柱状图（每日总计划/总实际 + 完成率线）。"""
    dates = data.get("dates", [])
    daily_summary = data.get("daily_summary", {})
    plan_data = []
    actual_data = []
    rate_data = []
    for d in dates:
        s = daily_summary.get(d, {})
        plan = s.get("total_plan", 0)
        actual = s.get("total_actual", 0)
        plan_data.append(plan)
        actual_data.append(actual)
        rate_data.append((actual / plan * 100) if plan > 0 else 0)

    return {
        "title": {"text": "每日总计划/实际数量与完成率"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"data": ["计划数量", "实际数量", "完成率"], "top": 30},
        "grid": {"left": "8%", "right": "8%", "bottom": "10%", "top": "20%"},
        "xAxis": {"type": "category", "data": dates},
        "yAxis": [
            {"type": "value", "name": "数量", "position": "left"},
            {"type": "value", "name": "完成率(%)", "position": "right", "min": 0, "max": 100},
        ],
        "series": [
            {"name": "计划数量", "type": "bar", "data": plan_data, "itemStyle": {"color": "#5470C6"}},
            {"name": "实际数量", "type": "bar", "data": actual_data, "itemStyle": {"color": "#91CC75"}},
            {
                "name": "完成率", "type": "line", "yAxisIndex": 1, "data": rate_data,
                "itemStyle": {"color": "#EE6666"}, "label": {"show": True, "formatter": "{c}%"},
            },
        ],
    }


def build_gantt_charts_html(data: dict) -> str:
    """构建所有项目甘特图HTML（纯HTML/CSS实现，避免ECharts custom series的边界过滤问题）。

    每个项目一个甘特图：
      - 顶部：日期表头
      - 每行一道工序，左侧工序名，右侧条形区
      - 蓝色条=计划区间，绿色条=实际完成比例（叠加在蓝色条上）
      - 红色边框=并行工序
      - 鼠标悬停显示详细信息
    """
    gantt_data = data.get("gantt_data", {})
    if not gantt_data:
        return '<div class="no-data">无甘特图数据</div>'

    sorted_items = sorted(gantt_data.items(), key=lambda x: x[1].get("dp_code", ""))
    html_parts = ['<h2>项目甘特图（蓝色=计划区间，绿色=实际完成，红色边框=并行工序）</h2>']

    for idx, (demand_id, product_data) in enumerate(sorted_items):
        if not product_data.get("processes"):
            continue

        dp_code = product_data.get("dp_code", "")
        product_name = product_data.get("product_name", "")
        proc_dict = product_data["processes"]
        proc_list = sorted(proc_dict.values(), key=lambda x: x.get("seq", 0))

        # 过滤无日期的工序
        valid_procs = [p for p in proc_list if p.get("first_plan_date") and p.get("last_plan_date")]
        if not valid_procs:
            html_parts.append(
                f'<div class="gantt-block">'
                f'<h3>{dp_code} - {product_name} ({len(proc_list)}道工序)</h3>'
                f'<div class="no-data">无有效日期数据</div>'
                f'</div>'
            )
            continue

        # 计算日期范围
        all_dates = []
        for p in valid_procs:
            d1 = parse_date(p["first_plan_date"])
            d2 = parse_date(p["last_plan_date"])
            if not all_dates:
                all_dates = [d1, d2]
            else:
                if d1 < all_dates[0]:
                    all_dates[0] = d1
                if d2 > all_dates[1]:
                    all_dates[1] = d2

        min_date = all_dates[0]
        max_date = all_dates[1]
        total_days = (max_date - min_date).days + 1

        # 生成日期列表
        date_list = []
        cur = min_date
        while cur <= max_date:
            date_list.append(cur)
            cur += timedelta(days=1)

        # 构建日期表头
        date_header_cells = []
        for d in date_list:
            is_weekend = d.weekday() >= 5
            cell_class = "gantt-date-weekend" if is_weekend else "gantt-date-weekday"
            date_header_cells.append(
                f'<div class="gantt-date-cell {cell_class}">{d.strftime("%m-%d")}</div>'
            )
        date_header = "".join(date_header_cells)

        # 构建每行工序
        proc_rows = []
        # 倒序显示（seq大的在下，seq小的在上）→ 正序排列，seq1在顶部
        for p in valid_procs:
            seq = p.get("seq", 0)
            name = p.get("process_name") or p.get("process_code") or p["process_id"][:8]
            is_parallel = p.get("is_parallel", False)
            plan_qty = p.get("plan_qty", 0) or 0
            actual_qty = p.get("actual_qty", 0) or 0
            first_date = parse_date(p["first_plan_date"])
            last_date = parse_date(p["last_plan_date"])

            # 计算条形位置（百分比）
            start_offset = (first_date - min_date).days
            end_offset = (last_date - min_date).days + 1  # +1使条覆盖到当天结束
            start_pct = (start_offset / total_days) * 100
            width_pct = ((end_offset - start_offset) / total_days) * 100

            # 实际完成比例
            if plan_qty > 0:
                ratio = min(actual_qty / plan_qty, 1.0)
            else:
                ratio = 1.0
            actual_width_pct = width_pct * ratio

            # 完成率
            rate = (actual_qty / plan_qty * 100) if plan_qty > 0 else 0
            rate_class = "rate-high" if rate >= 95 else ("rate-mid" if rate >= 80 else "rate-low")

            parallel_marker = "并行" if is_parallel else ""
            parallel_class = " gantt-bar-parallel" if is_parallel else ""

            # V3.2: 三时间参数显示
            cycle_time = p.get("cycle_time", 0) or 0
            prep_time = p.get("prep_time", 0) or 0
            wait_time = p.get("wait_time", 0) or 0
            wait_offhours = p.get("wait_includes_offhours", False)
            auto_type = p.get("auto_type", "非自动") or "非自动"
            max_units = p.get("max_units_per_beat", 1) or 1
            dep_type = p.get("dependency_type", "FS") or "FS"

            # 工序名（含参数标记）
            name_display = f"[并行] {name}" if is_parallel else name
            # wait_time>0 时在工序名后加 ⏳ 标记
            if wait_time > 0:
                name_display += f" ⏳{int(wait_time)}分"

            # 条形HTML（tooltip 增加三参数详情）
            bar_html = (
                f'<div class="gantt-bar-plan{parallel_class}" '
                f'style="left:{start_pct:.2f}%;width:{width_pct:.2f}%;" '
                f'title="{name} (seq={seq}, {dep_type})&#10;'
                f'计划: {p["first_plan_date"]} ~ {p["last_plan_date"]}&#10;'
                f'计划数: {plan_qty}&#10;'
                f'实际数: {actual_qty} ({rate:.1f}%)&#10;'
                f'--- 时间参数 ---&#10;'
                f'节拍cycle_time: {cycle_time}秒&#10;'
                f'准备prep_time: {prep_time}分&#10;'
                f'等待wait_time: {wait_time}分 (含下班: {wait_offhours})&#10;'
                f'工艺类型: {auto_type}, 单节拍最大: {max_units}&#10;'
                f'{parallel_marker}">'
                f'<div class="gantt-bar-actual" style="width:{actual_width_pct / width_pct * 100:.2f}%;" '
                f'title="实际完成: {actual_qty}/{plan_qty} ({rate:.1f}%)"></div>'
                f'<span class="gantt-bar-label">{plan_qty} / {actual_qty}</span>'
                f'</div>'
            )

            proc_rows.append(
                f'<div class="gantt-row">'
                f'<div class="gantt-row-label">{name_display}</div>'
                f'<div class="gantt-row-bars">{bar_html}</div>'
                f'</div>'
            )

        rows_html = "".join(proc_rows)

        html_parts.append(
            f'<div class="gantt-block">'
            f'<h3>{dp_code} - {product_name} ({len(valid_procs)}道工序)</h3>'
            f'<div class="gantt-table">'
            f'<div class="gantt-header">'
            f'<div class="gantt-row-label">工序</div>'
            f'<div class="gantt-header-dates">{date_header}</div>'
            f'</div>'
            f'{rows_html}'
            f'</div>'
            f'</div>'
        )

    return "\n".join(html_parts)


def build_html(data: dict, title: str, scheduling_mode: str = "capacity") -> str:
    """构建完整HTML报告。

    Args:
        scheduling_mode: 求解模式，显示在配置摘要中（capacity / time_exclusive）
    """
    config = data.get("config", {})
    dates = data.get("dates", [])
    processes = data.get("processes", [])
    gantt_data = data.get("gantt_data", {})

    overview_table = build_overview_table(data)
    process_option = build_process_chart_option(data)
    summary_option = build_summary_chart_option(data)
    gantt_html = build_gantt_charts_html(data)

    # 求解模式显示
    mode_label = "产能累加(日级)" if scheduling_mode == "capacity" else "时间独占(小时级)"

    # 配置摘要
    config_html = f"""
    <div class="config-summary">
      <h2>{title}</h2>
      <table class="config-table">
        <tr><td>需求数量</td><td>{config.get('num_demands', '-')}</td>
            <td>目标完成天数</td><td>{config.get('target_days', '-')}</td></tr>
        <tr><td>仿真天数</td><td>{config.get('sim_days', '-')}</td>
            <td>实际运行天数</td><td>{config.get('final_day', '-')}</td></tr>
        <tr><td>完成率范围</td><td>{config.get('min_rate', 0):.0%} - {config.get('max_rate', 0):.0%}</td>
            <td>排产窗口</td><td>{config.get('schedule_horizon', '-')}天</td></tr>
        <tr><td>仿真开始日期</td><td>{config.get('sim_start_date', '-')}</td>
            <td>随机种子</td><td>{config.get('seed', '-')}</td></tr>
        <tr><td>全部完成</td><td>{'是' if config.get('completed_all') else '否'}</td>
            <td>工序数</td><td>{len(processes)}</td></tr>
        <tr><td>求解模式</td><td>{scheduling_mode} - {mode_label}</td>
            <td>配置求解模式</td><td>{config.get('scheduling_mode', '-')}</td></tr>
      </table>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <script src="{ECHARTS_CDN}"></script>
  <style>
    body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 20px; background: #f5f5f5; }}
    h1 {{ text-align: center; color: #333; }}
    h2 {{ color: #444; border-left: 4px solid #5470C6; padding-left: 10px; margin-top: 30px; }}
    h3 {{ color: #555; margin-bottom: 10px; }}
    .config-summary {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .config-table {{ width: 100%; border-collapse: collapse; }}
    .config-table td {{ padding: 8px 12px; border: 1px solid #ddd; }}
    .config-table td:nth-child(odd) {{ background: #f9f9f9; font-weight: bold; width: 15%; }}
    .config-table td:nth-child(even) {{ width: 35%; }}
    .chart-block {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .gantt-block {{ background: white; padding: 15px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    table.data-table {{ width: 100%; border-collapse: collapse; background: white; }}
    table.data-table th, table.data-table td {{ padding: 8px; border: 1px solid #ddd; text-align: center; }}
    table.data-table th {{ background: #5470C6; color: white; }}
    .rate-high {{ color: #91CC75; font-weight: bold; }}
    .rate-mid {{ color: #FAC858; font-weight: bold; }}
    .rate-low {{ color: #EE6666; font-weight: bold; }}
    .no-data {{ color: #999; text-align: center; padding: 20px; }}

    /* 甘特图样式（纯HTML/CSS实现） */
    .gantt-table {{ border: 1px solid #ddd; border-radius: 4px; overflow: hidden; }}
    .gantt-header {{ display: flex; background: #f0f4f8; border-bottom: 2px solid #5470C6; height: 40px; align-items: center; }}
    .gantt-header-dates {{ display: flex; flex: 1; height: 100%; }}
    .gantt-date-cell {{ flex: 1; display: flex; align-items: center; justify-content: center; font-size: 11px; border-right: 1px solid #e0e0e0; min-width: 0; overflow: hidden; }}
    .gantt-date-weekend {{ background: #fff5f5; color: #c44; }}
    .gantt-date-weekday {{ color: #555; }}
    .gantt-row {{ display: flex; height: 38px; border-bottom: 1px solid #f0f0f0; align-items: center; }}
    .gantt-row:last-child {{ border-bottom: none; }}
    .gantt-row-label {{ width: 140px; min-width: 140px; padding: 0 10px; font-size: 12px; text-align: right; color: #333; border-right: 1px solid #ddd; height: 100%; display: flex; align-items: center; justify-content: flex-end; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
    .gantt-row-bars {{ flex: 1; position: relative; height: 100%; min-width: 0; }}
    .gantt-bar-plan {{ position: absolute; top: 6px; height: 26px; background: rgba(84, 112, 198, 0.3); border: 1px solid #5470C6; border-radius: 3px; cursor: pointer; overflow: hidden; min-width: 2px; }}
    .gantt-bar-parallel {{ border: 2px solid #EE6666; }}
    .gantt-bar-actual {{ position: absolute; top: 0; left: 0; height: 100%; background: rgba(145, 204, 117, 0.85); border-radius: 2px; min-width: 2px; }}
    .gantt-bar-label {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 10px; color: #333; white-space: nowrap; text-shadow: 0 0 3px rgba(255,255,255,0.8); pointer-events: none; }}
    .gantt-bar-plan:hover {{ background: rgba(84, 112, 198, 0.5); }}
    .gantt-legend {{ display: flex; gap: 20px; margin: 10px 0; font-size: 13px; flex-wrap: wrap; }}
    .gantt-legend-item {{ display: flex; align-items: center; gap: 6px; }}
    .gantt-legend-color {{ display: inline-block; width: 20px; height: 14px; border-radius: 2px; }}
  </style>
</head>
<body>
  <h1>多轮排产仿真测试报告</h1>
  {config_html}

  <h2>每日总览</h2>
  <table class="data-table">
    <thead><tr><th>日期</th><th>计划数量</th><th>实际数量</th><th>完成率</th></tr></thead>
    <tbody>
      {overview_table}
    </tbody>
  </table>

  <div class="chart-block">
    <div id="process-chart" style="width:100%;height:500px;"></div>
  </div>

  <div class="chart-block">
    <div id="summary-chart" style="width:100%;height:400px;"></div>
  </div>

  {gantt_html}

  <div class="gantt-legend">
    <div class="gantt-legend-item"><span class="gantt-legend-color" style="background: rgba(84, 112, 198, 0.3); border: 1px solid #5470C6;"></span>计划区间</div>
    <div class="gantt-legend-item"><span class="gantt-legend-color" style="background: rgba(145, 204, 117, 0.85);"></span>实际完成</div>
    <div class="gantt-legend-item"><span class="gantt-legend-color" style="background: rgba(84, 112, 198, 0.3); border: 2px solid #EE6666;"></span>并行工序</div>
    <div class="gantt-legend-item"><span>标签格式: 计划数 / 实际数</span></div>
  </div>

  <script>
    // 工序曲线图
    const processChart = echarts.init(document.getElementById('process-chart'));
    processChart.setOption({json.dumps(process_option, ensure_ascii=False, default=str)});

    // 汇总图
    const summaryChart = echarts.init(document.getElementById('summary-chart'));
    summaryChart.setOption({json.dumps(summary_option, ensure_ascii=False, default=str)});

    window.addEventListener('resize', () => {{
      processChart.resize();
      summaryChart.resize();
    }});
  </script>
</body>
</html>
"""
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="生成HTML仿真报告")
    parser.add_argument("--input", type=str, required=True, help="仿真数据JSON路径")
    parser.add_argument("--output", type=str, required=True, help="HTML输出路径")
    parser.add_argument("--title", type=str, default="排产仿真报告", help="报告标题")
    parser.add_argument(
        "--scheduling-mode",
        type=str,
        default="capacity",
        choices=["capacity", "time_exclusive"],
        help="求解模式（显示在报告配置摘要中）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    html = build_html(data, args.title, scheduling_mode=args.scheduling_mode)

    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML报告已生成: {args.output}")
    print(f"  文件大小: {os.path.getsize(args.output) / 1024:.1f} KB")
    print(f"  日期数: {len(data.get('dates', []))}")
    print(f"  项目数: {len(data.get('gantt_data', {}))}")


if __name__ == "__main__":
    main()
