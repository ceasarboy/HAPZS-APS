"""向 HAP 写入测试数据 - 修正 fields 格式为数组"""
import os
import httpx
import json
import time
from datetime import datetime, timedelta

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

field_cache = {}

def get_structure(ws_id):
    if ws_id in field_cache:
        return field_cache[ws_id]
    r = httpx.get(f"{BASE}/v3/app/worksheets/{ws_id}", headers=HEADERS, timeout=30)
    result = r.json()
    if result.get("success"):
        s = result["data"]
        field_cache[ws_id] = s
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

def make_field(fid, value):
    """构造单个字段对象"""
    return {"id": fid, "value": value}

def batch_create(ws_id, rows_data, batch_size=50):
    """批量创建记录，rows_data 是 fields 数组的列表"""
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

def create_single(ws_id, fields):
    """创建单条记录"""
    body = {"appId": APP_ID, "triggerWorkflow": False, "fields": fields}
    r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows", headers=HEADERS, json=body, timeout=30)
    result = r.json()
    if result.get("success"):
        data = result.get("data", {})
        return data if isinstance(data, str) else (data.get("rowId") or data.get("id"))
    else:
        print(f"  创建失败: {result.get('error_msg', '')[:200]}")
        return None

# ============================================================
# 1. 产品主数据
# ============================================================
print("=" * 60)
print("1. 创建产品主数据 (15 个产品)")
print("=" * 60)

products = [
    ("P001", "外壳-A1", "颜色A", 2, 50),
    ("P002", "外壳-A2", "颜色A", 2, 50),
    ("P003", "外壳-B1", "颜色B", 2, 40),
    ("P004", "外壳-B2", "颜色B", 2, 40),
    ("P005", "面板-C1", "颜色C", 3, 60),
    ("P006", "面板-C2", "颜色C", 3, 60),
    ("P007", "支架-D1", "模具类型1", 4, 80),
    ("P008", "支架-D2", "模具类型1", 4, 80),
    ("P009", "底座-E1", "模具类型2", 1, 30),
    ("P010", "底座-E2", "模具类型2", 1, 30),
    ("P011", "盖板-F1", "颜色A", 3, 50),
    ("P012", "盖板-F2", "颜色B", 3, 50),
    ("P013", "连接器-G1", "模具类型1", 5, 100),
    ("P014", "连接器-G2", "模具类型2", 5, 100),
    ("P015", "转接片-H1", "颜色C", 6, 120),
]

fid_code = get_fid(WS["product"], "product_code")
fid_name = get_fid(WS["product"], "product_name")
fid_attr = get_fid(WS["product"], "changeover_attr")
fid_rate = get_fid(WS["product"], "output_rate")
fid_batch = get_fid(WS["product"], "batch_size")

product_rows = []
for code, name, attr, rate, batch in products:
    fields = [
        make_field(fid_code, code),
        make_field(fid_name, name),
        make_field(fid_rate, rate),
        make_field(fid_batch, batch),
    ]
    key = get_opt_key(WS["product"], "changeover_attr", attr)
    if key:
        fields.append(make_field(fid_attr, [key]))
    product_rows.append({"fields": fields})

product_ids = batch_create(WS["product"], product_rows)
print(f"  产品: {len(product_ids)} 条")
time.sleep(1)

# ============================================================
# 2. 工作中心
# ============================================================
print("\n" + "=" * 60)
print("2. 创建工作中心 (4 条产线)")
print("=" * 60)

workcenters = [
    ("WC-A", "注塑产线A", "产线", 85, 600),
    ("WC-B", "注塑产线B", "产线", 82, 550),
    ("WC-C", "冲压产线C", "产线", 88, 500),
    ("WC-D", "装配产线D", "产线", 90, 450),
]

fid_code = get_fid(WS["work_center"], "wc_code")
fid_name = get_fid(WS["work_center"], "wc_name")
fid_type = get_fid(WS["work_center"], "wc_type")
fid_oee = get_fid(WS["work_center"], "oee")
fid_cap = get_fid(WS["work_center"], "daily_capacity")
fid_status = get_fid(WS["work_center"], "wc_status")

wc_rows = []
for code, name, wtype, oee, cap in workcenters:
    fields = [
        make_field(fid_code, code),
        make_field(fid_name, name),
        make_field(fid_oee, oee),
        make_field(fid_cap, cap),
    ]
    key = get_opt_key(WS["work_center"], "wc_type", wtype)
    if key:
        fields.append(make_field(fid_type, [key]))
    key = get_opt_key(WS["work_center"], "wc_status", "可用")
    if key:
        fields.append(make_field(fid_status, [key]))
    wc_rows.append({"fields": fields})

wc_ids = batch_create(WS["work_center"], wc_rows)
print(f"  工作中心: {len(wc_ids)} 条")
time.sleep(1)

# ============================================================
# 3. 生产日历
# ============================================================
print("\n" + "=" * 60)
print("3. 创建生产日历")
print("=" * 60)

today = datetime.now()
tomorrow = today + timedelta(days=1)

fid_no = get_fid(WS["production_calendar"], "cal_no")
fid_date = get_fid(WS["production_calendar"], "cal_date")
fid_shift = get_fid(WS["production_calendar"], "shift")
fid_start = get_fid(WS["production_calendar"], "start_time")
fid_end = get_fid(WS["production_calendar"], "end_time")
fid_cstatus = get_fid(WS["production_calendar"], "cal_status")
fid_wc = get_fid(WS["production_calendar"], "related_workcenter")

cal_rows = []
for day_offset in [0, 1]:
    cal_date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
    for shift_name, (start_h, end_h) in [("早班", (8, 14)), ("中班", (14, 20))]:
        for wc_idx, wc_id in enumerate(wc_ids):
            fields = [
                make_field(fid_no, f"CAL-{cal_date}-{shift_name}-{workcenters[wc_idx][0]}"),
                make_field(fid_date, cal_date),
                make_field(fid_start, f"{start_h:02d}:00"),
                make_field(fid_end, f"{end_h:02d}:00"),
                make_field(fid_wc, [wc_id]),
            ]
            key = get_opt_key(WS["production_calendar"], "shift", shift_name)
            if key:
                fields.append(make_field(fid_shift, [key]))
            key = get_opt_key(WS["production_calendar"], "cal_status", "可用")
            if key:
                fields.append(make_field(fid_cstatus, [key]))
            cal_rows.append({"fields": fields})

cal_ids = batch_create(WS["production_calendar"], cal_rows)
print(f"  生产日历: {len(cal_ids)} 条")
time.sleep(1)

# ============================================================
# 4. 生产订单 + 订单明细
# ============================================================
print("\n" + "=" * 60)
print("4. 创建生产订单 (20 个)")
print("=" * 60)

fid_no = get_fid(WS["production_order"], "order_no")
fid_pri = get_fid(WS["production_order"], "priority")
fid_ddate = get_fid(WS["production_order"], "delivery_date")
fid_ostatus = get_fid(WS["production_order"], "order_status")

priorities = ["高"] * 5 + ["中"] * 9 + ["低"] * 6
order_ids = []

for i in range(1, 21):
    delivery = (today + timedelta(days=2 + (i % 3))).strftime("%Y-%m-%d")
    fields = [
        make_field(fid_no, f"PO-2026-{i:04d}"),
        make_field(fid_ddate, delivery),
    ]
    key = get_opt_key(WS["production_order"], "priority", priorities[i-1])
    if key:
        fields.append(make_field(fid_pri, [key]))
    key = get_opt_key(WS["production_order"], "order_status", "待排产")
    if key:
        fields.append(make_field(fid_ostatus, [key]))
    rid = create_single(WS["production_order"], fields)
    if rid:
        order_ids.append(rid)

print(f"  生产订单: {len(order_ids)} 条")
time.sleep(1)

# 订单明细
print("\n  创建订单明细...")
fid_ino = get_fid(WS["order_item"], "item_no")
fid_dqty = get_fid(WS["order_item"], "demand_qty")
fid_sqty = get_fid(WS["order_item"], "scheduled_qty")
fid_idate = get_fid(WS["order_item"], "item_delivery_date")
fid_istatus = get_fid(WS["order_item"], "item_status")
fid_order = get_fid(WS["order_item"], "related_order")
fid_product = get_fid(WS["order_item"], "related_product")

quantities = [120, 100, 80, 150, 90, 110, 70, 130, 60, 140, 85, 95, 75, 105, 115, 65, 125, 55, 135, 100]
item_ids = []

for i, order_id in enumerate(order_ids):
    product_idx = i % len(product_ids)
    qty = quantities[i % len(quantities)]
    delivery = (today + timedelta(days=2 + (i % 3))).strftime("%Y-%m-%d")

    fields = [
        make_field(fid_ino, f"ITEM-{i+1:04d}"),
        make_field(fid_dqty, qty),
        make_field(fid_sqty, 0),
        make_field(fid_idate, delivery),
        make_field(fid_order, [order_id]),
        make_field(fid_product, [product_ids[product_idx]]),
    ]
    key = get_opt_key(WS["order_item"], "item_status", "待排产")
    if key:
        fields.append(make_field(fid_istatus, [key]))
    rid = create_single(WS["order_item"], fields)
    if rid:
        item_ids.append(rid)

print(f"  订单明细: {len(item_ids)} 条")
time.sleep(1)

# ============================================================
# 5. 换线矩阵
# ============================================================
print("\n" + "=" * 60)
print("5. 创建换线矩阵")
print("=" * 60)

fid_mno = get_fid(WS["changeover_matrix"], "matrix_no")
fid_ctime = get_fid(WS["changeover_matrix"], "changeover_time")
fid_ccost = get_fid(WS["changeover_matrix"], "changeover_cost")
fid_from = get_fid(WS["changeover_matrix"], "from_product")
fid_to = get_fid(WS["changeover_matrix"], "to_product")

attr_map = {}
for idx, p in enumerate(products):
    if idx < len(product_ids):
        attr_map[p[0]] = (p[2], product_ids[idx])

color_set = {"颜色A", "颜色B", "颜色C"}
mold_set = {"模具类型1", "模具类型2"}

def co_time(a1, a2):
    if a1 == a2:
        return 15
    if a1 in color_set and a2 in color_set:
        return 30
    if a1 in mold_set and a2 in mold_set:
        return 25
    return 45

co_rows = []
seen = set()
for from_code, (from_attr, from_id) in attr_map.items():
    for to_code, (to_attr, to_id) in attr_map.items():
        if from_code >= to_code:
            continue
        pair = (from_code, to_code)
        if pair in seen:
            continue
        seen.add(pair)
        ct = co_time(from_attr, to_attr)
        fields = [
            make_field(fid_mno, f"CO-{from_code}-{to_code}"),
            make_field(fid_ctime, ct),
            make_field(fid_ccost, ct * 10),
            make_field(fid_from, [from_id]),
            make_field(fid_to, [to_id]),
        ]
        co_rows.append({"fields": fields})

co_rows = co_rows[:50]
co_ids = batch_create(WS["changeover_matrix"], co_rows)
print(f"  换线矩阵: {len(co_ids)} 条")
time.sleep(1)

# ============================================================
# 6. 物料齐套
# ============================================================
print("\n" + "=" * 60)
print("6. 创建物料齐套")
print("=" * 60)

fid_mname = get_fid(WS["kitting_info"], "material_name")
fid_mcode = get_fid(WS["kitting_info"], "material_code")
fid_aqty = get_fid(WS["kitting_info"], "available_qty")
fid_tqty = get_fid(WS["kitting_info"], "in_transit_qty")
fid_sstock = get_fid(WS["kitting_info"], "safety_stock")
fid_adate = get_fid(WS["kitting_info"], "available_date")

materials = [
    ("ABS塑料颗粒", "MAT-001", 5000, 2000, 500, today.strftime("%Y-%m-%d")),
    ("PP塑料颗粒", "MAT-002", 3000, 1000, 300, today.strftime("%Y-%m-%d")),
    ("钢板卷材", "MAT-003", 2000, 800, 200, today.strftime("%Y-%m-%d")),
    ("铝合金型材", "MAT-004", 1500, 500, 150, today.strftime("%Y-%m-%d")),
    ("铜连接端子", "MAT-005", 8000, 3000, 800, today.strftime("%Y-%m-%d")),
    ("不锈钢螺栓", "MAT-006", 10000, 5000, 1000, today.strftime("%Y-%m-%d")),
    ("硅胶密封圈", "MAT-007", 6000, 2000, 600, today.strftime("%Y-%m-%d")),
    ("PCB电路板", "MAT-008", 1200, 400, 120, tomorrow.strftime("%Y-%m-%d")),
]

kit_rows = []
for name, code, qty, transit, safety, date in materials:
    fields = [
        make_field(fid_mname, name),
        make_field(fid_mcode, code),
        make_field(fid_aqty, qty),
        make_field(fid_tqty, transit),
        make_field(fid_sstock, safety),
        make_field(fid_adate, date),
    ]
    kit_rows.append({"fields": fields})

kit_ids = batch_create(WS["kitting_info"], kit_rows)
print(f"  物料齐套: {len(kit_ids)} 条")

# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 60)
print("测试数据创建完成！")
print("=" * 60)
print(f"  产品主数据: {len(product_ids)} 条")
print(f"  工作中心:   {len(wc_ids)} 条")
print(f"  生产日历:   {len(cal_ids)} 条")
print(f"  生产订单:   {len(order_ids)} 条")
print(f"  订单明细:   {len(item_ids)} 条")
print(f"  换线矩阵:   {len(co_ids)} 条")
print(f"  物料齐套:   {len(kit_ids)} 条")
total_qty = sum(quantities[i % len(quantities)] for i in range(len(order_ids)))
print(f"  总需求量:   {total_qty} 台")
