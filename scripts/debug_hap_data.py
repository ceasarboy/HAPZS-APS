"""调试：查看 HAP 返回的实际数据结构"""
import os
import httpx
import json

APP_ID = os.environ.get("HAP_APP_ID", "")
HEADERS = {
    "Content-Type": "application/json",
    "HAP-Appkey": os.environ.get("HAP_APPKEY", ""),
    "HAP-Sign": os.environ.get("HAP_SIGN", ""),
}
BASE = "https://api.mingdao.com"

# 读取订单明细第1条
body = {"appId": APP_ID, "pageSize": 1}
r = httpx.post(f"{BASE}/v3/app/worksheets/6a2bf82888359ed35897e135/rows/list", headers=HEADERS, json=body, timeout=30)
result = r.json()
if result.get("success"):
    rows = result.get("data", {}).get("rows", [])
    if rows:
        print("第1条订单明细的完整数据:")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    else:
        print("无数据")
else:
    print(f"失败: {result.get('error_msg')}")

print("\n" + "=" * 60)

# 读取工作中心第1条
r2 = httpx.post(f"{BASE}/v3/app/worksheets/6a2bf81a9e6cd05a84b842ca/rows/list", headers=HEADERS, json=body, timeout=30)
result2 = r2.json()
if result2.get("success"):
    rows2 = result2.get("data", {}).get("rows", [])
    if rows2:
        print("第1条工作中心的完整数据:")
        print(json.dumps(rows2[0], ensure_ascii=False, indent=2))
