"""
排产求解 + 结果推送 HAP 完整闭环脚本
从 HAP 读取订单/日历/工作中心/换线矩阵 → ortools CP-SAT 求解 → 结果推送回 HAP
"""
import os
import httpx
import json
import time
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

# ============================================================
# HAP 配置（从环境变量读取，或设置 .env 文件）
# ============================================================
APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}
BASE = "https://api.mingdao.com"

WS = {
    "product": "6a2bf816c839766934ee62e8",
    "work_center": "6a2bf81a9e6cd05a84b842ca",
    "production_order": "6a2bf822777a8aa776d5bd72",
    "order_item": "6a2bf82888359ed35897e135",
    "changeover_matrix": "6a2bf82eb650d46f3d1a4f70",
    "kitting_info": "6a2bf8329702ee83242eb628",
    "schedule_result": "6a2bf837c00b1ea7c04743f3",
    "production_calendar": "6a2bf89d7a04850bc82c0845",
}

# ============================================================
# HAP 数据读取
# ============================================================
structure_cache = {}

def get_structure(ws_id):
    """获取工作表结构"""
    if ws_id in structure_cache:
        return structure_cache[ws_id]
    r = httpx.get(f"{BASE}/v3/app/worksheets/{ws_id}", headers=HEADERS, timeout=30)
    result = r.json()
    if result.get("success"):
        s = result["data"]
        structure_cache[ws_id] = s
        return s
    return None

def get_fid(ws_id, alias):
    s = get_structure(ws_id)
    if not s:
        return None
    for f in s.get("fields", []):
        if f.get("alias") == alias or f.get("name") == alias:
            return f.get("fieldId") or f.get("id")
    return None

def get_opt_key(ws_id, alias, display_value):
    s = get_structure(ws_id)
    if not s:
        return None
    for f in s.get("fields", []):
        if f.get("alias") == alias or f.get("name") == alias:
            for opt in f.get("options", []):
                if opt.get("value") == display_value:
                    return opt.get("key")
    return None

def get_opt_value(ws_id, alias, key):
    """根据 key 获取显示值"""
    s = get_structure(ws_id)
    if not s:
        return None
    for f in s.get("fields", []):
        if f.get("alias") == alias or f.get("name") == alias:
            for opt in f.get("options", []):
                if opt.get("key") == key:
                    return opt.get("value")
    return None

def fetch_rows(ws_id, filter_obj=None, page_size=200):
    """从 HAP 拉取记录"""
    body = {"appId": APP_ID, "pageSize": page_size}
    if filter_obj:
        body["filter"] = filter_obj
    r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows/list", headers=HEADERS, json=body, timeout=30)
    result = r.json()
    if result.get("success"):
        data = result.get("data", {})
        return data.get("rows") or data or []
    else:
        print(f"  拉取失败: {result.get('error_msg', '')[:200]}")
        return []

def batch_create(ws_id, rows_data, batch_size=50):
    """批量创建记录"""
    total = len(rows_data)
    created = 0
    row_ids = []
    for i in range(0, total, batch_size):
        batch = rows_data[i:i+batch_size]
        body = {"appId": APP_ID, "triggerWorkflow": False, "rows": batch}
        r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows/batch", headers=HEADERS, json=body, timeout=60)
        result = r.json()
        if result.get("success"):
            data = result.get("data", {})
            ids = data if isinstance(data, list) else (data.get("rowIds") or data.get("ids") or [])
            row_ids.extend(ids)
            created += len(batch)
            print(f"  批次 {i//batch_size+1}: {len(batch)} 条成功 (累计 {created}/{total})")
        else:
            print(f"  批次 {i//batch_size+1}: 失败 - {result.get('error_msg', '')[:300]}")
        time.sleep(0.5)
    return row_ids

# ============================================================
# 第一步：从 HAP 读取数据
# ============================================================
print("=" * 60)
print("第一步：从 HAP 读取数据")
print("=" * 60)

# 1. 读取订单明细（含关联的订单和产品信息）
print("\n读取订单明细...")
item_rows = fetch_rows(WS["order_item"])
print(f"  订单明细: {len(item_rows)} 条")

# 2. 读取工作中心
print("读取工作中心...")
wc_rows = fetch_rows(WS["work_center"])
print(f"  工作中心: {len(wc_rows)} 条")

# 3. 读取生产日历
print("读取生产日历...")
cal_rows = fetch_rows(WS["production_calendar"])
print(f"  生产日历: {len(cal_rows)} 条")

# 4. 读取换线矩阵
print("读取换线矩阵...")
co_rows = fetch_rows(WS["changeover_matrix"])
print(f"  换线矩阵: {len(co_rows)} 条")

# ============================================================
# 第二步：数据解析与建模
# ============================================================
print("\n" + "=" * 60)
print("第二步：数据解析与建模")
print("=" * 60)

# HAP 返回数据直接用 alias 作为 key
# 解析订单明细
items = []
for row in item_rows:
    item = {
        "rowid": row.get("rowId", ""),
        "demand_qty": float(row.get("demand_qty", "0") or "0"),
        "scheduled_qty": float(row.get("scheduled_qty", "0") or "0"),
        "product_name": "",
        "product_rowid": "",
        "order_no": "",
    }
    # 关联产品
    product_rel = row.get("related_product", [])
    if isinstance(product_rel, list) and len(product_rel) > 0:
        item["product_rowid"] = product_rel[0].get("sid", "") if isinstance(product_rel[0], dict) else ""
        item["product_name"] = product_rel[0].get("name", "") if isinstance(product_rel[0], dict) else ""
    # 关联订单
    order_rel = row.get("related_order", [])
    if isinstance(order_rel, list) and len(order_rel) > 0:
        item["order_no"] = order_rel[0].get("name", "") if isinstance(order_rel[0], dict) else ""
    items.append(item)

# 解析工作中心
workcenters = []
for row in wc_rows:
    wc = {
        "rowid": row.get("rowId", ""),
        "code": row.get("wc_code", ""),
        "name": row.get("wc_name", ""),
        "oee": float(row.get("oee", "85") or "85"),
        "daily_capacity": float(row.get("daily_capacity", "500") or "500"),
    }
    workcenters.append(wc)

# 解析日历 → 构建时间槽
# 今天早班 08:00-14:00 (6小时=6个时间槽)，中班 14:00-20:00 (6小时=6个时间槽)
today = datetime.now().strftime("%Y-%m-%d")
time_slots = []
for hour in range(8, 20):
    time_slots.append(f"{hour:02d}:00")

print(f"  时间槽: {len(time_slots)} 个 ({time_slots[0]} ~ {time_slots[-1]})")
print(f"  订单明细: {len(items)} 个 (总需求 {sum(i['demand_qty'] for i in items):.0f} 台)")
print(f"  工作中心: {len(workcenters)} 条")
print(f"  换线矩阵: {len(co_rows)} 条")

# ============================================================
# 第三步：ortools CP-SAT 求解
# ============================================================
print("\n" + "=" * 60)
print("第三步：ortools CP-SAT 求解")
print("=" * 60)

T = len(time_slots)    # 12 个时间槽
W = len(workcenters)   # 4 条产线
I = len(items)         # 20 个订单明细

# 每个时间槽每条产线的产能（台/小时），基于 OEE 和日产能
capacity = []
for w in range(W):
    hourly_cap = workcenters[w]["daily_capacity"] / 12  # 日产能/12小时
    effective_cap = hourly_cap * workcenters[w]["oee"] / 100
    capacity.append(max(1, int(effective_cap)))

print(f"  产线小时产能: {capacity}")

# 创建 CP-SAT 模型
model = cp_model.CpModel()

# 决策变量：x[i][t][w] = 订单明细 i 在时间槽 t 在产线 w 上生产的数量
x = {}
for i in range(I):
    for t in range(T):
        for w in range(W):
            x[i, t, w] = model.NewIntVar(0, capacity[w], f"x_{i}_{t}_{w}")

# 约束1：每个时间槽每条产线的总产量不超过产能
for t in range(T):
    for w in range(W):
        model.Add(sum(x[i, t, w] for i in range(I)) <= capacity[w])

# 约束2：每个订单明细的总产量不超过需求量（允许部分满足）
# 引入未满足量变量用于目标函数惩罚
unmet = {}
for i in range(I):
    demand = int(items[i]["demand_qty"])
    unmet[i] = model.NewIntVar(0, demand, f"unmet_{i}")
    total_produced = sum(x[i, t, w] for t in range(T) for w in range(W))
    model.Add(total_produced + unmet[i] == demand)

# 约束3：换线约束 - 同一产线同一时间槽最多只能生产一种产品
# 引入布尔变量：y[i][t][w] = 1 表示订单明细 i 在时间槽 t 在产线 w 上有生产
y = {}
for i in range(I):
    for t in range(T):
        for w in range(W):
            y[i, t, w] = model.NewBoolVar(f"y_{i}_{t}_{w}")
            # 如果 x > 0 则 y = 1
            model.Add(x[i, t, w] > 0).OnlyEnforceIf(y[i, t, w])
            model.Add(x[i, t, w] == 0).OnlyEnforceIf(y[i, t, w].Not())

# 每个时间槽每条产线最多生产 1 种产品
for t in range(T):
    for w in range(W):
        model.Add(sum(y[i, t, w] for i in range(I)) <= 1)

# 约束4：换线次数惩罚
# z[i][j][t][w] = 1 表示产线 w 在时间槽 t 从产品 i 切换到产品 j
# 简化：统计相邻时间槽产品切换次数
changeover_count = model.NewIntVar(0, T * W, "changeover_count")
changeover_terms = []
for t in range(1, T):
    for w in range(W):
        for i in range(I):
            for j in range(I):
                if i == j:
                    continue
                # 产线 w 在 t-1 生产 i，在 t 生产 j → 换线
                both = model.NewBoolVar(f"co_{i}_{j}_{t}_{w}")
                model.AddBoolAnd([y[i, t-1, w], y[j, t, w]]).OnlyEnforceIf(both)
                model.AddBoolOr([y[i, t-1, w].Not(), y[j, t, w].Not()]).OnlyEnforceIf(both.Not())
                changeover_terms.append(both)

model.Add(changeover_count == sum(changeover_terms))

# 约束5：负荷均衡 - 各产线总产量尽量接近
total_demand = sum(int(items[i]["demand_qty"]) for i in range(I))
avg_per_line = total_demand // W
max_deviation = model.NewIntVar(0, total_demand, "max_deviation")
for w in range(W):
    line_total = sum(x[i, t, w] for i in range(I) for t in range(T))
    diff_pos = model.NewIntVar(0, total_demand, f"diff_pos_{w}")
    model.Add(diff_pos >= line_total - avg_per_line)
    model.Add(diff_pos >= avg_per_line - line_total)
    model.Add(max_deviation >= diff_pos)

# 目标函数：最小化未满足量（最高优先）+ 换线次数 + 负荷偏差
total_unmet = sum(unmet[i] for i in range(I))
model.Minimize(total_unmet * 100 + changeover_count * 10 + max_deviation * 1)

# 求解
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 30
solver.parameters.num_workers = 4

print("  开始求解...")
start_time = time.time()
status = solver.Solve(model)
elapsed = time.time() - start_time

print(f"  求解状态: {solver.StatusName(status)}")
print(f"  求解耗时: {elapsed:.2f} 秒")
if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    print(f"  换线次数: {solver.Value(changeover_count)}")
    print(f"  负荷偏差: {solver.Value(max_deviation)}")
    total_unmet_val = sum(solver.Value(unmet[i]) for i in range(I))
    print(f"  未满足量: {total_unmet_val} 台")
else:
    print("  无可行解！")
    exit(1)

# ============================================================
# 第四步：解析求解结果
# ============================================================
print("\n" + "=" * 60)
print("第四步：解析求解结果")
print("=" * 60)

results = []  # [{time_slot, workcenter, product, quantity, item_idx}]
for t in range(T):
    for w in range(W):
        for i in range(I):
            qty = solver.Value(x[i, t, w])
            if qty > 0:
                results.append({
                    "time_slot": time_slots[t],
                    "workcenter_idx": w,
                    "item_idx": i,
                    "quantity": qty,
                })

print(f"  排产结果: {len(results)} 条记录")

# 打印计划矩阵
print("\n  计划矩阵:")
header = f"  {'时间':>8s}"
for w in range(W):
    header += f"  {workcenters[w]['code']:>12s}"
print(header)
print("  " + "-" * (8 + 14 * W))

for t in range(T):
    line = f"  {time_slots[t]:>8s}"
    for w in range(W):
        cell = ""
        for r in results:
            if r["time_slot"] == time_slots[t] and r["workcenter_idx"] == w:
                pname = items[r["item_idx"]]["product_name"][:6]
                cell = f"{pname}:{r['quantity']}"
                break
        line += f"  {cell:>12s}"
    print(line)

# 负荷统计
print("\n  产线负荷:")
for w in range(W):
    total = sum(r["quantity"] for r in results if r["workcenter_idx"] == w)
    max_cap = capacity[w] * T
    rate = total / max_cap * 100 if max_cap > 0 else 0
    print(f"    {workcenters[w]['code']}: {total} 台 / {max_cap} 台 = {rate:.1f}%")

# ============================================================
# 第五步：推送结果到 HAP
# ============================================================
print("\n" + "=" * 60)
print("第五步：推送结果到 HAP")
print("=" * 60)

# 先清除排产结果表中的旧数据
old_results = fetch_rows(WS["schedule_result"])
if old_results:
    old_ids = []
    for r in old_results:
        if isinstance(r, dict):
            rid = r.get("rowId") or r.get("rowid")
            if rid:
                old_ids.append(rid)
    if old_ids:
        for i in range(0, len(old_ids), 100):
            batch_ids = old_ids[i:i+100]
            r = httpx.request("DELETE", f"{BASE}/v3/app/worksheets/{WS['schedule_result']}/rows/batch",
                              headers=HEADERS, json={"appId": APP_ID, "rowIds": batch_ids}, timeout=30)
            print(f"  清除旧数据: {len(batch_ids)} 条")
        time.sleep(1)

# 获取排产结果表的字段 ID
sr_fid_map = {f.get("alias", f.get("name")): f.get("fieldId") or f.get("id")
              for f in get_structure(WS["schedule_result"]).get("fields", [])}

# 构建写入数据
batch_no = f"SCH-{datetime.now().strftime('%Y%m%d-%H%M')}"
sr_rows = []

for r in results:
    i = r["item_idx"]
    w = r["workcenter_idx"]
    fields = []

    # 排产编号
    fid = sr_fid_map.get("schedule_no")
    if fid:
        fields.append({"id": fid, "value": f"{batch_no}-{r['time_slot']}-{workcenters[w]['code']}-{i+1:03d}"})

    # 时间段（选项 key）
    fid = sr_fid_map.get("time_slot")
    if fid:
        key = get_opt_key(WS["schedule_result"], "time_slot", r["time_slot"])
        if key:
            fields.append({"id": fid, "value": [key]})

    # 计划数量
    fid = sr_fid_map.get("planned_qty")
    if fid:
        fields.append({"id": fid, "value": r["quantity"]})

    # 结果状态（选项 key）
    fid = sr_fid_map.get("result_status")
    if fid:
        key = get_opt_key(WS["schedule_result"], "result_status", "计划中")
        if key:
            fields.append({"id": fid, "value": [key]})

    # 排产批次
    fid = sr_fid_map.get("schedule_batch")
    if fid:
        fields.append({"id": fid, "value": batch_no})

    # 关联订单明细
    fid = sr_fid_map.get("related_order_item")
    if fid and items[i]["rowid"]:
        fields.append({"id": fid, "value": [items[i]["rowid"]]})

    # 工作中心
    fid = sr_fid_map.get("related_workcenter")
    if fid and workcenters[w]["rowid"]:
        fields.append({"id": fid, "value": [workcenters[w]["rowid"]]})

    sr_rows.append({"fields": fields})

# 批量写入
result_ids = batch_create(WS["schedule_result"], sr_rows)
print(f"\n  排产结果推送: {len(result_ids)} 条")

# ============================================================
# 第六步：更新订单明细的"已排数量"
# ============================================================
print("\n" + "=" * 60)
print("第六步：更新订单明细已排数量")
print("=" * 60)

for i, item in enumerate(items):
    scheduled = sum(r["quantity"] for r in results if r["item_idx"] == i)
    if scheduled > 0 and item["rowid"]:
        fields = []
        fid = get_fid(WS["order_item"], "scheduled_qty")
        if fid:
            fields.append({"id": fid, "value": scheduled})
        fid = get_fid(WS["order_item"], "item_status")
        if fid:
            if scheduled >= item["demand_qty"]:
                key = get_opt_key(WS["order_item"], "item_status", "已排完")
            else:
                key = get_opt_key(WS["order_item"], "item_status", "部分排")
            if key:
                fields.append({"id": fid, "value": [key]})

        if fields:
            body = {"appId": APP_ID, "triggerWorkflow": False, "fields": fields}
            httpx.put(f"{BASE}/v3/app/worksheets/{WS['order_item']}/rows/{item['rowid']}",
                      headers=HEADERS, json=body, timeout=30)

print(f"  已更新 {len(items)} 条订单明细的已排数量")

# ============================================================
# 完成
# ============================================================
print("\n" + "=" * 60)
print("排产完成！")
print("=" * 60)
print(f"  排产批次: {batch_no}")
print(f"  排产结果: {len(result_ids)} 条已推送 HAP")
print(f"  总产量: {sum(r['quantity'] for r in results)} 台")
print(f"  换线次数: {solver.Value(changeover_count)}")
print(f"  请在明道云中查看: https://www.mingdao.com/app/{APP_ID}")
