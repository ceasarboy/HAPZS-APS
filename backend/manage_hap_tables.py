"""HAP 工作表管理脚本 - 新增4张表 + 修改4张现有表"""
import os
import httpx
import json
import time
from pathlib import Path

APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}
BASE_URL = "https://api.mingdao.com"
# 相对于本文件定位仓库根目录下的 deploy/worksheet_ids.json（不再硬编码盘符）
IDS_FILE = Path(__file__).resolve().parents[1] / "deploy" / "worksheet_ids.json"

# 加载已有工作表 ID
with open(IDS_FILE, "r", encoding="utf-8") as f:
    worksheet_ids = json.load(f)


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
# 第一步：创建4张新工作表（不含关联字段）
# ============================================================

print("=" * 60)
print("第一步：创建4张新工作表")
print("=" * 60)

# 1. 工艺路径
if "process_route" not in worksheet_ids:
    create_worksheet("工艺路径", "process_route", [
        {"name": "路径编号", "alias": "route_code", "type": "Text", "isTitle": True, "required": True},
        {"name": "工序序号", "alias": "process_seq", "type": "Number", "required": True},
        {"name": "工序名称", "alias": "process_name", "type": "Text", "required": True},
        {"name": "标准工时", "alias": "std_time", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "是否瓶颈", "alias": "is_bottleneck", "type": "SingleSelect", "required": False,
         "options": opt(["是", "否"]), "defaultValue": opt(["否"])},
        {"name": "固化时间", "alias": "cure_time", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "转移时间", "alias": "transfer_time", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "是否占用资源", "alias": "occupy_resource", "type": "SingleSelect", "required": False,
         "options": opt(["是", "否"]), "defaultValue": opt(["是"])},
    ])
    time.sleep(1)
else:
    print(f"\n跳过工艺路径 (已存在: {worksheet_ids['process_route']})")

# 2. 资源日历
if "resource_calendar" not in worksheet_ids:
    create_worksheet("资源日历", "resource_calendar", [
        {"name": "日历编号", "alias": "calendar_code", "type": "Text", "isTitle": True, "required": True},
        {"name": "日期", "alias": "cal_date", "type": "Date", "required": True},
        {"name": "班次", "alias": "shift", "type": "SingleSelect", "required": True,
         "options": opt(["早班", "中班", "晚班"])},
        {"name": "可用产能", "alias": "available_capacity", "type": "Number", "required": True},
        {"name": "人员技能标签", "alias": "skill_tags", "type": "Text", "required": False},
        {"name": "设备状态", "alias": "equipment_status", "type": "SingleSelect", "required": False,
         "options": opt(["正常", "维护中", "停机"]), "defaultValue": opt(["正常"])},
    ])
    time.sleep(1)
else:
    print(f"\n跳过资源日历 (已存在: {worksheet_ids['resource_calendar']})")

# 3. 缓冲配置
if "buffer_config" not in worksheet_ids:
    create_worksheet("缓冲配置", "buffer_config", [
        {"name": "解耦点编号", "alias": "decoupling_code", "type": "Text", "isTitle": True, "required": True},
        {"name": "缓冲类型", "alias": "buffer_type", "type": "SingleSelect", "required": True,
         "options": opt(["时间缓冲", "库存缓冲", "物流缓冲", "工艺缓冲"])},
        {"name": "缓冲时长", "alias": "buffer_duration", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "安全区阈值", "alias": "safe_threshold", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "警戒区阈值", "alias": "warning_threshold", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
        {"name": "危险区阈值", "alias": "danger_threshold", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
    ])
    time.sleep(1)
else:
    print(f"\n跳过缓冲配置 (已存在: {worksheet_ids['buffer_config']})")

# 4. 排产方案
if "schedule_plan" not in worksheet_ids:
    create_worksheet("排产方案", "schedule_plan", [
        {"name": "方案编号", "alias": "plan_code", "type": "Text", "isTitle": True, "required": True},
        {"name": "方案类型", "alias": "plan_type", "type": "SingleSelect", "required": True,
         "options": opt(["日常排产", "紧急插单", "What-if模拟"])},
        {"name": "综合得分", "alias": "overall_score", "type": "Number", "required": False, "decimalPlaces": 2},
        {"name": "OTD达成率", "alias": "otd_rate", "type": "Number", "required": False, "unit": "%", "decimalPlaces": 2},
        {"name": "换线次数", "alias": "changeover_count", "type": "Number", "required": False},
        {"name": "产线均衡率", "alias": "balance_rate", "type": "Number", "required": False, "unit": "%", "decimalPlaces": 2},
        {"name": "瓶颈利用率", "alias": "bottleneck_util", "type": "Number", "required": False, "unit": "%", "decimalPlaces": 2},
        {"name": "总产量", "alias": "total_output", "type": "Number", "required": False},
        {"name": "状态", "alias": "plan_status", "type": "SingleSelect", "required": False,
         "options": opt(["待确认", "已确认", "已取消"]), "defaultValue": opt(["待确认"])},
        {"name": "创建时间", "alias": "create_time", "type": "Date", "required": False},
    ])
else:
    print(f"\n跳过排产方案 (已存在: {worksheet_ids['schedule_plan']})")

# ============================================================
# 第二步：添加关联字段到新表
# ============================================================

print("\n" + "=" * 60)
print("第二步：添加关联字段到新表")
print("=" * 60)

time.sleep(2)

# 工艺路径 → 产品
if "product" in worksheet_ids and "process_route" in worksheet_ids:
    print(f"\n工艺路径 → 产品")
    add_fields(worksheet_ids["process_route"], [
        {"name": "产品", "alias": "related_product", "type": "Relation",
         "dataSource": worksheet_ids["product"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 工艺路径 → 工作中心
if "work_center" in worksheet_ids and "process_route" in worksheet_ids:
    print(f"\n工艺路径 → 工作中心")
    add_fields(worksheet_ids["process_route"], [
        {"name": "工作中心", "alias": "related_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 资源日历 → 工作中心
if "work_center" in worksheet_ids and "resource_calendar" in worksheet_ids:
    print(f"\n资源日历 → 工作中心")
    add_fields(worksheet_ids["resource_calendar"], [
        {"name": "工作中心", "alias": "related_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 缓冲配置 → 前序工作中心
if "work_center" in worksheet_ids and "buffer_config" in worksheet_ids:
    print(f"\n缓冲配置 → 前序工作中心")
    add_fields(worksheet_ids["buffer_config"], [
        {"name": "前序工作中心", "alias": "pre_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# 缓冲配置 → 后序工作中心
if "work_center" in worksheet_ids and "buffer_config" in worksheet_ids:
    print(f"\n缓冲配置 → 后序工作中心")
    add_fields(worksheet_ids["buffer_config"], [
        {"name": "后序工作中心", "alias": "post_workcenter", "type": "Relation",
         "dataSource": worksheet_ids["work_center"], "subType": "1", "required": True},
    ])
    time.sleep(1)

# ============================================================
# 第三步：修改4张现有工作表（添加字段）
# ============================================================

print("\n" + "=" * 60)
print("第三步：修改4张现有工作表")
print("=" * 60)

time.sleep(2)

# 1. 产品主数据 - 添加产线兼容码
print(f"\n产品主数据 - 添加产线兼容码")
add_fields(worksheet_ids["product"], [
    {"name": "产线兼容码", "alias": "line_compat_code", "type": "Text", "required": False},
])
time.sleep(1)

# 2. 订单明细 - 添加加工批量、流转批量
print(f"\n订单明细 - 添加加工批量、流转批量")
add_fields(worksheet_ids["order_item"], [
    {"name": "加工批量", "alias": "process_batch", "type": "Number", "required": False},
    {"name": "流转批量", "alias": "transfer_batch", "type": "Number", "required": False},
])
time.sleep(1)

# 3. 换线矩阵 - 添加工艺相似度
print(f"\n换线矩阵 - 添加工艺相似度")
add_fields(worksheet_ids["changeover_matrix"], [
    {"name": "工艺相似度", "alias": "process_similarity", "type": "Number", "required": False, "decimalPlaces": 2},
])
time.sleep(1)

# 4. 排产结果 - 添加工序序号、缓冲类型、缓冲时长
print(f"\n排产结果 - 添加工序序号、缓冲类型、缓冲时长")
add_fields(worksheet_ids["schedule_result"], [
    {"name": "工序序号", "alias": "process_seq", "type": "Number", "required": False},
    {"name": "缓冲类型", "alias": "buffer_type", "type": "SingleSelect", "required": False,
     "options": opt(["无", "时间缓冲", "库存缓冲", "物流缓冲", "工艺缓冲"])},
    {"name": "缓冲时长", "alias": "buffer_duration", "type": "Number", "required": False, "unit": "小时", "decimalPlaces": 2},
])
time.sleep(1)

# 排产结果 → 排产方案（关联字段需要 schedule_plan 已创建）
if "schedule_plan" in worksheet_ids:
    print(f"\n排产结果 → 排产方案")
    add_fields(worksheet_ids["schedule_result"], [
        {"name": "关联方案", "alias": "related_plan", "type": "Relation",
         "dataSource": worksheet_ids["schedule_plan"], "subType": "1", "required": False},
    ])

# ============================================================
# 汇总
# ============================================================

print("\n" + "=" * 60)
print("操作结果汇总")
print("=" * 60)

print("\n新建工作表:")
for alias in ["process_route", "resource_calendar", "buffer_config", "schedule_plan"]:
    ws_id = worksheet_ids.get(alias, "未创建")
    print(f"  {alias}: {ws_id}")

print("\n修改工作表:")
for alias in ["product", "order_item", "changeover_matrix", "schedule_result"]:
    ws_id = worksheet_ids.get(alias, "未知")
    print(f"  {alias}: {ws_id}")

# 保存更新后的 ID
with open(IDS_FILE, "w", encoding="utf-8") as f:
    json.dump(worksheet_ids, f, ensure_ascii=False, indent=2)
print(f"\n工作表 ID 已更新保存到 {IDS_FILE}")
