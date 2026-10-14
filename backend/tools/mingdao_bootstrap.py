"""明道云 NEDIAPS 空白应用初始化：创建 MPS 四表单并导入种子数据。

用法（backend 目录，项目内嵌 Python）：
  $env:MINGDAO_APPKEY="<appkey>"; $env:MINGDAO_SIGN="<sign>"
  python tools/mingdao_bootstrap.py --list         # 打印应用与表单/行数
  python tools/mingdao_bootstrap.py --create       # 创建表单（已存在则复用本地登记）
  python tools/mingdao_bootstrap.py --load         # 导入数据（行已存在则跳过）
  python tools/mingdao_bootstrap.py --reload-rows  # 清空四表单行后重导

凭据仅从环境变量读取（不落盘、不入库）：
  MINGDAO_APPKEY / MINGDAO_SIGN / MINGDAO_APPID（默认 NEDIAPS）/ MD_BASE（默认 api.mingdao.com）
表单 ID 登记在 backend/.tmp/mingdao_ids.json（已被 .gitignore 忽略）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

BASE = os.environ.get("MD_BASE", "https://api.mingdao.com")
APP_ID = os.environ.get("MINGDAO_APPID", "c542d5c8-097b-4e5d-b29a-12240c32ba9d")
SEED_DIR = Path(__file__).resolve().parents[1] / "app" / "seed"
REGISTRY = Path(__file__).resolve().parents[1] / ".tmp" / "mingdao_ids.json"


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "HAP-Appkey": os.environ["MINGDAO_APPKEY"],
        "HAP-Sign": os.environ["MINGDAO_SIGN"],
    }


# ────────────────────────── 表单定义（MPS 数据模型 → 明道云） ──────────────────────────

def _title(name, alias):
    return {"name": name, "alias": alias, "type": "Text", "isTitle": True, "required": True}


def _text(name, alias, required=False):
    return {"name": name, "alias": alias, "type": "Text", "required": required}


def _num(name, alias, unit=None, required=False):
    f = {"name": name, "alias": alias, "type": "Number", "required": required}
    if unit:
        f["unit"] = unit
    return f


def _date(name, alias):
    return {"name": name, "alias": alias, "type": "Date", "required": False}


def _sel(name, alias, options, required=False):
    return {
        "name": name, "alias": alias, "type": "SingleSelect", "required": required,
        "options": [{"value": v} for v in options],
    }


WORKSHEETS: dict[str, dict] = {
    "process_master": {
        "name": "工序主数据",
        "fields": [
            _title("工序键", "pm_key"),
            _sel("级别", "level", ["芯片级", "模块级", "组件级"]),
            _text("工序", "op"),
            _text("生产模式", "mode"),
            _num("基准周期(天)", "cycle"),
            _num("一次装配合格率", "yield_assembly"),
            _num("一次检验合格率", "yield_inspect"),
            _num("综合成品率", "yield_overall"),
            _num("单工位日产能", "cap_station"),
            _num("工位数", "stations"),
            _num("基准均值通量", "flux_base"),
            _num("基准峰值通量", "flux_peak"),
            _text("核算单位", "unit"),
            _text("特征参数名", "feature"),
            _text("分流规则", "split_rule"),
            _num("分流阈值", "split_threshold", unit="只"),
            _text("周期调节说明", "cycle_note"),
            _text("备注", "remark"),
        ],
    },
    "process_set": {
        "name": "成套工艺",
        "fields": [
            _title("工艺代号", "code"),
            _text("产品形态", "form"),
            _text("封装架构", "arch"),
            _text("名称", "name"),
            _text("特征说明", "feature"),
            _text("版本", "version"),
            _text("路线原文", "route_text"),
            _text("负责人", "owner"),
            _num("成品率", "yield_ref"),
            _num("装配放量比", "ratio_ref"),
            _num("单件装配周期(天)", "cycle_ref"),
            _num("加急单件周期(天)", "urgent_ref"),
            _text("分部件模式", "subpart_mode"),
            _num("分部件周期(天)", "subpart_cycle"),
            _num("爬坡时间(天)", "ramp_days"),
            _text("瓶颈工序", "bottleneck_op"),
            _num("瓶颈通量", "bottleneck_flux"),
            _text("水汽要求说明", "water_note"),
            _sel("状态", "status", ["启用", "停用"]),
            _text("备注", "remark"),
        ],
    },
    "process_route": {
        "name": "工艺路线",
        "fields": [
            _title("路线键", "route_key"),
            _text("工艺代号", "code"),
            _num("工序序号", "seq"),
            _text("工序原文名", "step_raw"),
            _text("规范工序名", "step_std"),
            _text("适用级别", "level"),
            _num("装配周期(天)", "cycle"),
            _num("一次检验合格率", "yield_inspect"),
            _num("综合成品率", "yield_overall"),
            _text("核算特征", "feature"),
            _text("折算系数", "cf_field"),
            _text("触发条件", "cf_trigger"),
            _text("备注", "note"),
        ],
    },
    "order": {
        "name": "工单",
        "fields": [
            _title("订单号", "order_no"),
            _text("产品型号", "product"),
            _text("工艺代号", "code"),
            _sel("订单类型", "order_type", ["常规", "加急"]),
            _sel("首单标记", "first_flag", ["否", "首单", "复线", "变更首件"]),
            _sel("水汽要求", "water_vapor", ["有", "无"]),
            _num("计划批量", "qty", unit="只"),
            _date("需求日期", "due_date"),
            _date("物料齐套时间", "kit_date"),
            _num("排产优先级", "priority"),
            _text("备注", "remark"),
            _num("N_b/单只植球数", "n_b"),
            _num("N_fc/单只倒装元件数", "n_fc"),
            _num("N_smt/单只贴装元件数", "n_smt"),
            _num("N_die/单只芯片数", "n_die"),
            _num("DB/胶水类型数", "y_die"),
            _num("N_wire/单只键合根丝数", "n_wire"),
            _num("WB/引线类型数", "y_wire"),
            _num("N_die-2/第2组芯片数", "n_die2"),
            _num("DB/第2组胶水类型数", "y_die2"),
            _num("N_wire-2/第2组键合根丝数", "n_wire2"),
            _num("WB/第2组引线类型数", "y_wire2"),
            _num("N_bs/单只钎焊部件数", "n_bs"),
            _num("N_a/单只电装点数", "n_a"),
            _num("投料量", "input_qty", unit="只"),
            _num("成品率(链)", "y_full"),
            _num("装配放量比", "yield_ratio"),
            _num("单件周期(天)", "cycle_single"),
            _num("采用通量", "adopted_flux"),
            _text("瓶颈工序", "bottleneck_op"),
            _num("批量总装配周期(天)", "cycle_batch"),
            _num("爬坡(天)", "ramp_applied"),
            _num("交付周期(天)", "delivery_cycle"),
            _date("最晚投料日", "latest_start_date"),
            _date("排产开始日", "plan_start_date"),
            _date("排产完成日", "plan_finish_date"),
            _num("交期余量(天)", "gap_days"),
            _sel("交期判定", "judge", ["满足", "零裕量", "延期", "无交期"]),
            _text("采用策略", "strategy_id"),
        ],
    },
}

# ────────────────────────── 数据装载（种子 → 明道云行） ──────────────────────────

FEATURE_ALIASES = {
    "N_b": "n_b", "N_fc": "n_fc", "N_smt": "n_smt", "N_die": "n_die",
    "Y_die": "y_die", "N_wire": "n_wire", "Y_wire": "y_wire",
    "N_die2": "n_die2", "Y_die2": "y_die2", "N_wire2": "n_wire2", "Y_wire2": "y_wire2",
    "N_bs": "n_bs", "N_a": "n_a",
}

SEL_FIELDS = {"level", "status", "order_type", "first_flag", "water_vapor", "judge"}


def _seed() -> dict:
    return json.loads((SEED_DIR / "mps_seed.json").read_text(encoding="utf-8"))


def _demo_orders() -> list[dict]:
    return json.loads((SEED_DIR / "demo_orders.json").read_text(encoding="utf-8"))


def build_rows() -> dict[str, list[dict]]:
    seed = _seed()
    rows: dict[str, list[dict]] = {}
    rows["process_master"] = [
        {
            "pm_key": f"{w['level']}|{w['op']}|{w['mode']}",
            "level": w["level"], "op": w["op"], "mode": w["mode"], "cycle": w["cycle"],
            "yield_assembly": w.get("yield_assembly"), "yield_inspect": w.get("yield_inspect"),
            "yield_overall": w.get("yield_overall"), "cap_station": w.get("cap_station"),
            "stations": w.get("stations"), "flux_base": w.get("flux_base"),
            "flux_peak": w.get("flux_peak"), "unit": w.get("unit"), "feature": w.get("feature"),
            "split_rule": w.get("split_rule"), "split_threshold": w.get("split_threshold"),
            "cycle_note": w.get("cycle_note"), "remark": w.get("remark"),
        }
        for w in seed["workcenters"]
    ]
    rows["process_set"] = [
        {
            "code": p["code"], "form": p.get("form"), "arch": p.get("arch"), "name": p.get("name"),
            "feature": p.get("feature"), "version": p.get("version"), "route_text": p.get("route_text"),
            "owner": p.get("owner"), "yield_ref": p.get("yield_ref"), "ratio_ref": p.get("ratio_ref"),
            "cycle_ref": p.get("cycle_ref"), "urgent_ref": p.get("urgent_ref"),
            "subpart_mode": p.get("subpart_mode"), "subpart_cycle": p.get("subpart_cycle"),
            "ramp_days": p.get("ramp_days"), "bottleneck_op": p.get("bottleneck_op"),
            "bottleneck_flux": p.get("bottleneck_flux"), "water_note": p.get("water_note"),
            "status": p.get("status") or "启用", "remark": p.get("remark"),
        }
        for p in seed["processes"]
    ]
    rows["process_route"] = [
        {
            "route_key": f"{r['code']}#{r['seq']}", "code": r["code"], "seq": r["seq"],
            "step_raw": r["step_raw"], "step_std": r["step_std"], "level": r["level"],
            "cycle": r.get("cycle"), "yield_inspect": r.get("yield_inspect"),
            "yield_overall": r.get("yield_overall"), "feature": r.get("feature"),
            "cf_field": r.get("cf_field"), "cf_trigger": r.get("cf_trigger"), "note": r.get("note"),
        }
        for r in seed["routes"]
    ]
    orders = []
    for o in _demo_orders():
        row = {
            "order_no": o["order_no"], "product": o["product"], "code": o["code"],
            "order_type": o["order_type"], "first_flag": o["first_flag"],
            "water_vapor": o["water_vapor"], "qty": o["qty"], "due_date": o.get("due_date"),
            "kit_date": o.get("kit_date"), "priority": o.get("priority"),
            "remark": o.get("remark") or None,
        }
        for k, v in (o.get("features") or {}).items():
            if k in FEATURE_ALIASES:
                row[FEATURE_ALIASES[k]] = v
        orders.append(row)
    rows["order"] = orders
    return rows


# ────────────────────────── API 交互 ──────────────────────────

def get_app() -> dict:
    r = httpx.get(f"{BASE}/v3/app", headers=_headers(), timeout=30)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用失败: {data}")
    return data["data"]


def create_worksheet(name: str, alias: str, fields: list[dict]) -> str:
    body = {"appId": APP_ID, "name": name, "alias": alias, "fields": fields}
    r = httpx.post(f"{BASE}/v3/app/worksheets", headers=_headers(), json=body, timeout=60)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"创建表单 {name} 失败: {data.get('error_msg') or data}")
    d = data.get("data", {})
    return d.get("worksheetId") or d.get("id") or d.get("workSheetId") or ""


def get_structure(ws_id: str) -> dict:
    r = httpx.get(f"{BASE}/v3/app/worksheets/{ws_id}", headers=_headers(), timeout=30)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"读取表单结构失败 {ws_id}: {data.get('error_msg') or data}")
    return data["data"]


def field_maps(struct: dict) -> tuple[dict, dict]:
    """返回 (alias→fieldId, alias→{值:optionKey})。"""
    ids: dict[str, str] = {}
    opts: dict[str, dict] = {}
    for f in struct.get("fields", []):
        alias = f.get("alias")
        if not alias:
            continue
        ids[alias] = f.get("fieldId") or f.get("id")
        if f.get("options"):
            opts[alias] = {o.get("value"): o.get("key") for o in f["options"]}
    return ids, opts


def rows_count(ws_id: str) -> int:
    body = {"appId": APP_ID, "worksheetId": ws_id, "pageIndex": 1, "pageSize": 1}
    r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows/list", headers=_headers(), json=body, timeout=30)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"统计行数失败 {ws_id}: {data.get('error_msg') or data}")
    return int(data.get("data", {}).get("total", 0))


def all_row_ids(ws_id: str) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        body = {"appId": APP_ID, "worksheetId": ws_id,
                "pageIndex": page, "pageSize": 1000, "responseFormat": "id"}
        r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows/list", headers=_headers(), json=body, timeout=60)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"列举行失败 {ws_id}: {data.get('error_msg') or data}")
        rows = data.get("data", {}).get("rows", [])
        ids += [x.get("rowId") or x.get("id") for x in rows]
        total = int(data.get("data", {}).get("total", 0))
        if len(ids) >= total or not rows:
            return ids
        page += 1


def delete_rows(ws_id: str, row_ids: list[str]) -> None:
    body = {"appId": APP_ID, "worksheetId": ws_id, "rowIds": row_ids}
    r = httpx.request("DELETE", f"{BASE}/v3/app/worksheets/{ws_id}/rows",
                      headers=_headers(), json=body, timeout=120)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"删除行失败 {ws_id}: {data.get('error_msg') or data}")


def to_fields(row: dict, ids: dict, opts: dict) -> list[dict]:
    out = []
    for alias, value in row.items():
        if value is None or value == "":
            continue
        fid = ids.get(alias)
        if not fid:
            raise KeyError(f"字段别名不存在: {alias}")
        if alias in SEL_FIELDS and opts.get(alias):
            value = opts[alias].get(value, value)
        out.append({"id": fid, "value": value})
    return out


def batch_insert(ws_id: str, rows: list[dict], ids: dict, opts: dict, batch_size: int = 50) -> int:
    created = 0
    for i in range(0, len(rows), batch_size):
        batch = [{"fields": to_fields(r, ids, opts)} for r in rows[i:i + batch_size]]
        body = {"appId": APP_ID, "triggerWorkflow": False, "rows": batch}
        r = httpx.post(f"{BASE}/v3/app/worksheets/{ws_id}/rows/batch",
                       headers=_headers(), json=body, timeout=120)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"批量导入失败 {ws_id} 第 {i // batch_size + 1} 批: {data.get('error_msg') or data}")
        created += len(batch)
        print(f"    {ws_id}: {created}/{len(rows)}")
        time.sleep(0.3)
    return created


# ────────────────────────── 主流程 ──────────────────────────

def _load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {}


def _save_registry(reg: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_create() -> None:
    app = get_app()
    print(f"应用: {app.get('name')} ({app.get('appId')})")
    reg = _load_registry()
    for alias, spec in WORKSHEETS.items():
        if reg.get(alias):
            print(f"  复用已登记表单 {spec['name']} ({alias}): {reg[alias]}")
            continue
        ws_id = create_worksheet(spec["name"], alias, spec["fields"])
        reg[alias] = ws_id
        _save_registry(reg)
        print(f"  创建 {spec['name']} ({alias}): {ws_id}")
        time.sleep(0.5)
    print("登记文件:", REGISTRY)


def cmd_load(reload: bool) -> None:
    reg = _load_registry()
    rows = build_rows()
    for alias, spec in WORKSHEETS.items():
        ws_id = reg.get(alias)
        if not ws_id:
            raise RuntimeError(f"表单未创建: {alias}（先运行 --create）")
        if reload:
            ids = all_row_ids(ws_id)
            if ids:
                delete_rows(ws_id, ids)
                print(f"  已清空 {spec['name']}: {len(ids)} 行")
        total = rows_count(ws_id)
        if total > 0:
            print(f"  跳过 {spec['name']}（已有 {total} 行；如需重导用 --reload-rows）")
            continue
        struct = get_structure(ws_id)
        ids_map, opts = field_maps(struct)
        print(f"  导入 {spec['name']} ({len(rows[alias])} 行)…")
        batch_insert(ws_id, rows[alias], ids_map, opts)


def cmd_list() -> None:
    app = get_app()
    print(f"应用: {app.get('name')} ({app.get('appId')}) | 组织: {app.get('organizationId')}")
    reg = _load_registry()
    for alias, spec in WORKSHEETS.items():
        ws_id = reg.get(alias)
        if not ws_id:
            print(f"  {spec['name']} ({alias}): 未创建")
            continue
        total = rows_count(ws_id)
        print(f"  {spec['name']} ({alias}): {ws_id} | {total} 行")


def main() -> None:
    parser = argparse.ArgumentParser(description="明道云 NEDIAPS 应用初始化（MPS 四表单+种子数据）")
    parser.add_argument("--create", action="store_true", help="创建表单")
    parser.add_argument("--load", action="store_true", help="导入数据（已存在则跳过）")
    parser.add_argument("--reload-rows", action="store_true", help="清空后重导数据")
    parser.add_argument("--list", action="store_true", help="列出表单与行数")
    args = parser.parse_args()
    if not any([args.create, args.load, args.reload_rows, args.list]):
        args.create = args.load = True

    if args.list:
        cmd_list()
        return
    if args.create:
        cmd_create()
    if args.load or args.reload_rows:
        cmd_load(reload=args.reload_rows)


if __name__ == "__main__":
    main()
