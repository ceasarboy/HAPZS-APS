"""把 mps-web 种子转换为本系统种子文件（只读 D:\\MPS，一次运行，产物入库）。

用法：在 backend 目录执行  python tools/convert_mps_seed.py
产物：app/seed/mps_seed.json、app/seed/demo_orders.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MPS_WEB = Path(r"D:\MPS\mps-web")
OUT = Path(__file__).resolve().parents[1] / "app" / "seed"


def build() -> dict:
    src = json.loads((MPS_WEB / "seed.json").read_text(encoding="utf-8"))

    workcenters = []
    for w in src["workcenters"]:
        for m in w["modes"]:
            workcenters.append({
                "level": w["level"], "op": w["op"], "mode": m["mode"],
                "cycle": m["cycle"], "yield_assembly": m.get("yield_assembly"),
                "yield_inspect": m.get("yield_inspect"), "yield_overall": m.get("yield_overall"),
                "cap_station": m.get("cap_station"), "stations": m.get("stations"),
                "flux_base": m.get("flux_base"), "flux_peak": m.get("flux_peak"),
                "unit": m.get("unit"), "feature": m.get("feature"),
                "split_rule": m.get("split_rule"), "split_threshold": m.get("split_threshold"),
                "cycle_note": None, "remark": m.get("note"),
            })

    processes = [{
        "code": p["code"], "form": p.get("form") or None, "arch": p.get("arch") or None,
        "name": p.get("name"), "feature": p.get("feature"), "version": p.get("version"),
        "route_text": p.get("route_text"), "owner": p.get("owner") or None,
        "yield_ref": p.get("yield_ref"), "ratio_ref": p.get("ratio_ref"),
        "cycle_ref": p.get("cycle_ref"), "urgent_ref": p.get("urgent_ref"),
        "required_flags": p.get("required_flags"),
        "subpart_mode": p.get("subpart_mode") or None, "subpart_cycle": p.get("subpart_cycle") or None,
        "ramp_days": p.get("ramp_days"), "bottleneck_op": None, "bottleneck_flux": None,
        "water_note": p.get("note") or None, "status": "启用", "remark": p.get("note") or None,
    } for p in src["processes"]]

    routes = [{
        "code": r["code"], "seq": r["seq"], "step_raw": r["step_raw"], "step_std": r["step_std"],
        "level": r["level"], "cycle": r.get("cycle"), "yield_inspect": r.get("yield_inspect"),
        "yield_overall": r.get("yield_overall"), "feature": r.get("feature"),
        "cf_field": r.get("cf_field"), "cf_trigger": r.get("cf_trigger"),
        "note": r.get("note") or None,
    } for r in src["routes"]]

    p = src["params"]
    params = {
        "week_days": str(p["week_days"]),
        "peak_factor": str(p["peak_factor"]),
        "exclude_braze_yield": str(p["exclude_braze_yield_for_component"]),
        "cf_db_1": str(p["cf_db_by_glue_count"]["1"]),
        "cf_db_2": str(p["cf_db_by_glue_count"]["2"]),
        "cf_db_3": str(p["cf_db_by_glue_count"]["3"]),
        "cf_wb_1": str(p["cf_wb_by_wire_count"]["1"]),
        "cf_wb_2": str(p["cf_wb_by_wire_count"]["2"]),
        "cf_wb_3": str(p["cf_wb_by_wire_count"]["3"]),
    }
    return {"version": 1, "source": "mps-web seed.json (V1.7)",
            "workcenters": workcenters, "processes": processes, "routes": routes, "params": params}


def main() -> None:
    out = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mps_seed.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    orders = json.loads((MPS_WEB / "sample_orders.json").read_text(encoding="utf-8"))
    demo = [{
        "order_no": o["order_no"], "product": o["product"], "code": o["code"],
        "order_type": o["order_type"], "first_flag": o["first_flag"], "water_vapor": o["water_vapor"],
        "qty": o["qty"], "due_date": o.get("due_date"), "kit_date": o.get("kit_date"),
        "priority": o.get("priority"), "features": o.get("features"), "remark": o.get("remark") or "",
    } for o in orders]
    (OUT / "demo_orders.json").write_text(json.dumps(demo, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"workcenters={len(out['workcenters'])} processes={len(out['processes'])} "
          f"routes={len(out['routes'])} orders={len(demo)}")


if __name__ == "__main__":
    main()
