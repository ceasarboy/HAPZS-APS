"""单独创建生产日历工作表"""
import os
import httpx, json, time

APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}
BASE = "https://api.mingdao.com"
WC_ID = "6a2bf81a9e6cd05a84b842ca"  # 工作中心 ID

def opt(v):
    return [{"value": x} for x in v]

body = {
    "appId": APP_ID,
    "name": "生产日历",
    "alias": "production_calendar",
    "fields": [
        {"name": "日历编号", "alias": "cal_no", "type": "Text", "isTitle": True, "required": True},
        {"name": "日期", "alias": "cal_date", "type": "Date", "required": True, "subType": "3"},
        {"name": "班次", "alias": "shift", "type": "SingleSelect", "required": True,
         "options": opt(["早班", "中班", "晚班"])},
        {"name": "开始时间", "alias": "start_time", "type": "Time", "required": True, "subType": "1"},
        {"name": "结束时间", "alias": "end_time", "type": "Time", "required": True, "subType": "1"},
        {"name": "状态", "alias": "cal_status", "type": "SingleSelect", "required": True,
         "options": opt(["可用", "不可用", "维护"])},
    ]
}

r = httpx.post(f"{BASE}/v3/app/worksheets", headers=HEADERS, json=body, timeout=30)
result = r.json()
print(f"创建生产日历: success={result.get('success')}")

if result.get("success"):
    ws_id = result["data"].get("worksheetId") or result["data"].get("id")
    print(f"  ID: {ws_id}")
    time.sleep(1)

    # 添加关联字段：工作中心
    r2 = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}", headers=HEADERS, json={
        "appId": APP_ID,
        "addFields": [{"name": "工作中心", "alias": "related_workcenter", "type": "Relation",
                       "dataSource": WC_ID, "subType": "1", "required": False}]
    }, timeout=30)
    print(f"  添加关联字段: success={r2.json().get('success')}")

    # 更新 worksheet_ids.json
    ids_file = "e:/openaps/aps-hap/deploy/worksheet_ids.json"
    with open(ids_file, "r", encoding="utf-8") as f:
        ids = json.load(f)
    ids["production_calendar"] = ws_id
    with open(ids_file, "w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False, indent=2)
    print("  已更新 worksheet_ids.json")
else:
    print(f"  失败: {result.get('error_msg', '')}")
