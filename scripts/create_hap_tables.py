"""HAP 工作表创建脚本 - 修正版（选项格式 + 标题字段类型修复）"""
import os
import httpx
import json
import time

APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}
BASE_URL = "https://api.mingdao.com"

worksheet_ids = {}

def opt(values):
    """将字符串列表转为 HAP 选项对象格式"""
    return [{"value": v} for v in values]

def create_worksheet(name, alias, fields):
    """创建工作表"""
    body = {"appId": APP_ID, "name": name, "alias": alias, "fields": fields}
    print(f"\n创建工作表: {name} ({alias})")
    r = httpx.post(f"{BASE_URL}/v3/app/worksheets", headers=HEADERS, json=body, timeout=30)
    result = r.json()
    if result.get("success"):
        data = result.get("data", {})
        ws_id = data.get("worksheetId") or data.get("id") or data.get("workSheetId")
        worksheet_ids[alias] = ws_id
        print(f"  ✓ 成功! ID: {ws_id}")
        return ws_id
    else:
        print(f"  ✗ 失败: {result.get('error_msg', r.text[:300])}")
        return None

def add_fields(worksheet_id, fields):
    """向已有工作表添加字段"""
    body = {"appId": APP_ID, "addFields": fields}
    print(f"  添加字段: {[f['name'] for f in fields]}")
    r = httpx.post(f"{BASE_URL}/v3/app/worksheets/{worksheet_id}", headers=HEADERS, json=body, timeout=30)
    result = r.json()
    if result.get("success"):
        print(f"  ✓ 字段添加成功")
        return True
    else:
        print(f"  ✗ 字段添加失败: {result.get('error_msg', r.text[:300])}")
        return False

# ============================================================
# 第一步：创建工作表（含选项字段，暂不含关联字段）
# ============================================================

print("=" * 60)
print("第一步：创建工作表")
print("=" * 60)

# 1. 产品主数据
create_worksheet("产品主数据", "product", [
    {"name": "产品编码", "alias": "product_code", "type": "Text", "isTitle": True, "required": True},
    {"name": "产品名称", "alias": "product_name", "type": "Text", "required": True},
    {"name": "换线属性", "alias": "changeover_attr", "type": "SingleSelect", "required": False,
     "options": opt(["颜色A", "颜色B", "颜色C", "模具类型1", "模具类型2"])},
    {"name": "出件率", "alias": "output_rate", "type": "Number", "required": False, "unit": "件/次"},
    {"name": "整批量", "alias": "batch_size", "type": "Number", "required": False, "unit": "件"},
    {"name": "备注", "alias": "remark", "type": "Text", "required": False},
])
time.sleep(1)

# 2. 工作中心
create_worksheet("工作中心", "work_center", [
    {"name": "编码", "alias": "wc_code", "type": "Text", "isTitle": True, "required": True},
    {"name": "名称", "alias": "wc_name", "type": "Text", "required": True},
    {"name": "类型", "alias": "wc_type", "type": "SingleSelect", "required": True,
     "options": opt(["产线", "设备", "工位"])},
    {"name": "OEE", "alias": "oee", "type": "Number", "required": False, "unit": "%"},
    {"name": "日产能", "alias": "daily_capacity", "type": "Number", "required": False, "unit": "件/天"},
    {"name": "状态", "alias": "wc_status", "type": "SingleSelect", "required": False,
     "options": opt(["可用", "维护中", "停机"])},
])
time.sleep(1)

# 3. 生产订单
create_worksheet("生产订单", "production_order", [
    {"name": "订单编号", "alias": "order_no", "type": "Text", "isTitle": True, "required": True},
    {"name": "优先级", "alias": "priority", "type": "SingleSelect", "required": True,
     "options": opt(["高", "中", "低"])},
    {"name": "交付日期", "alias": "delivery_date", "type": "Date", "required": True},
    {"name": "状态", "alias": "order_status", "type": "SingleSelect", "required": True,
     "options": opt(["待排产", "已排产", "部分排", "已下发", "已完成"])},
    {"name": "描述", "alias": "description", "type": "Text", "required": False},
])
time.sleep(1)

# 4. 生产日历
create_worksheet("生产日历", "production_calendar", [
    {"name": "日期", "alias": "cal_date", "type": "Date", "isTitle": True, "required": True},
    {"name": "班次", "alias": "shift", "type": "SingleSelect", "required": True,
     "options": opt(["早班", "中班", "晚班"])},
    {"name": "开始时间", "alias": "start_time", "type": "Time", "required": True},
    {"name": "结束时间", "alias": "end_time", "type": "Time", "required": True},
    {"name": "状态", "alias": "cal_status", "type": "SingleSelect", "required": True,
     "options": opt(["可用", "不可用", "维护"])},
])
time.sleep(1)

# 5. 订单明细（标题字段用 Text，Number 不能做标题）
create_worksheet("订单明细", "order_item", [
    {"name": "明细编号", "alias": "item_no", "type": "Text", "isTitle": True, "required": True},
    {"name": "需求数量", "alias": "demand_qty", "type": "Number", "required": True, "unit": "件"},
    {"name": "已排数量", "alias": "scheduled_qty", "type": "Number", "required": False, "unit": "件"},
    {"name": "交付时间", "alias": "item_delivery_date", "type": "Date", "required": True},
    {"name": "明细状态", "alias": "item_status", "type": "SingleSelect", "required": False,
     "options": opt(["待排产", "部分排", "已排完"])},
])
time.sleep(1)

# 6. 换线矩阵（标题字段用 Text）
create_worksheet("换线矩阵", "changeover_matrix", [
    {"name": "矩阵编号", "alias": "matrix_no", "type": "Text", "isTitle": True, "required": True},
    {"name": "换线时间", "alias": "changeover_time", "type": "Number", "required": True, "unit": "分钟"},
    {"name": "换线成本", "alias": "changeover_cost", "type": "Number", "required": False},
])
time.sleep(1)

# 7. 物料齐套
create_worksheet("物料齐套", "kitting_info", [
    {"name": "物料名称", "alias": "material_name", "type": "Text", "isTitle": True, "required": True},
    {"name": "物料编码", "alias": "material_code", "type": "Text", "required": True},
    {"name": "可用数量", "alias": "available_qty", "type": "Number", "required": True, "unit": "件"},
    {"name": "在途数量", "alias": "in_transit_qty", "type": "Number", "required": False, "unit": "件"},
    {"name": "安全库存", "alias": "safety_stock", "type": "Number", "required": False, "unit": "件"},
    {"name": "可用日期", "alias": "available_date", "type": "Date", "required": True},
])
time.sleep(1)

# 8. 排产结果（标题字段用 Text，时间段改为 Text）
create_worksheet("排产结果", "schedule_result", [
    {"name": "排产编号", "alias": "schedule_no", "type": "Text", "isTitle": True, "required": True},
    {"name": "时间段", "alias": "time_slot", "type": "SingleSelect", "required": True,
     "options": opt(["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"])},
    {"name": "计划数量", "alias": "planned_qty", "type": "Number", "required": True, "unit": "件"},
    {"name": "结果状态", "alias": "result_status", "type": "SingleSelect", "required": True,
     "options": opt(["计划中", "已确认", "已下发", "已完工"])},
    {"name": "排产批次", "alias": "schedule_batch", "type": "Text", "required": False},
])

# ============================================================
# 第二步：添加关联字段
# ============================================================

print("\n" + "=" * 60)
print("第二步：添加关联字段")
print("=" * 60)

time.sleep(2)

# 订单明细 → 生产订单
if "production_order" in worksheet_ids and "order_item" in worksheet_ids:
    print(f"\n订单明细 → 生产订单")
    add_fields(worksheet_ids["order_item"], [
        {"name": "关联订单", "alias": "related_order", "type": "Relation",
         "dataSource": worksheet_ids["production_order"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 订单明细 → 产品主数据
if "product" in worksheet_ids and "order_item" in worksheet_ids:
    print(f"\n订单明细 → 产品主数据")
    add_fields(worksheet_ids["order_item"], [
        {"name": "产品", "alias": "related_product", "type": "Relation",
         "dataSource": worksheet_ids["product"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 生产日历 → 工作中心
if "work_center" in worksheet_ids and "production_calendar" in worksheet_ids:
    print(f"\n生产日历 → 工作中心")
    add_fields(worksheet_ids["production_calendar"], [
        {"name": "工作中心", "alias": "related_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": False},
    ])
    time.sleep(1)

# 换线矩阵 → 产品主数据
if "product" in worksheet_ids and "changeover_matrix" in worksheet_ids:
    print(f"\n换线矩阵 → 产品主数据")
    add_fields(worksheet_ids["changeover_matrix"], [
        {"name": "当前产品", "alias": "from_product", "type": "Relation",
         "dataSource": worksheet_ids["product"], "subType": "1", "required": True},
        {"name": "下一产品", "alias": "to_product", "type": "Relation",
         "dataSource": worksheet_ids["product"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 排产结果 → 订单明细
if "order_item" in worksheet_ids and "schedule_result" in worksheet_ids:
    print(f"\n排产结果 → 订单明细")
    add_fields(worksheet_ids["schedule_result"], [
        {"name": "关联订单明细", "alias": "related_order_item", "type": "Relation",
         "dataSource": worksheet_ids["order_item"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 排产结果 → 工作中心
if "work_center" in worksheet_ids and "schedule_result" in worksheet_ids:
    print(f"\n排产结果 → 工作中心")
    add_fields(worksheet_ids["schedule_result"], [
        {"name": "工作中心", "alias": "related_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 工作中心 → 工作中心（上级，自关联）
if "work_center" in worksheet_ids:
    print(f"\n工作中心 → 工作中心（自关联）")
    add_fields(worksheet_ids["work_center"], [
        {"name": "上级", "alias": "parent_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": False},
    ])

# ============================================================
# 汇总
# ============================================================

print("\n" + "=" * 60)
print("创建结果汇总")
print("=" * 60)
for alias, ws_id in worksheet_ids.items():
    print(f"  {alias}: {ws_id}")

with open("e:/openaps/aps-hap/deploy/worksheet_ids.json", "w", encoding="utf-8") as f:
    json.dump(worksheet_ids, f, ensure_ascii=False, indent=2)
print(f"\n工作表 ID 已保存到 deploy/worksheet_ids.json")
