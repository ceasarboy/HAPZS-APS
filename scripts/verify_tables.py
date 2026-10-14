"""验证 HAP 工作表创建结果"""
import os
import httpx

APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}

ids = {
    "product": "6a2bf816c839766934ee62e8",
    "work_center": "6a2bf81a9e6cd05a84b842ca",
    "production_order": "6a2bf822777a8aa776d5bd72",
    "order_item": "6a2bf82888359ed35897e135",
    "changeover_matrix": "6a2bf82eb650d46f3d1a4f70",
    "kitting_info": "6a2bf8329702ee83242eb628",
    "schedule_result": "6a2bf837c00b1ea7c04743f3",
    "production_calendar": "6a2bf89d7a04850bc82c0845",
}

for name, ws_id in ids.items():
    r = httpx.get(f"https://api.mingdao.com/v3/app/worksheets/{ws_id}", headers=HEADERS)
    result = r.json()
    if result.get("success"):
        fields = [f["name"] for f in result["data"].get("fields", [])]
        print(f"{name}: {len(fields)} fields => {fields}")
    else:
        print(f"{name}: ERROR - {result.get('error_msg', '')}")
