"""MPS 核算内核（移植自 mps-web src/engine.js；口径对齐《SiP产线成套工艺计算逻辑说明书-V1.6》）。

约定：
- 纯函数：输入订单 dict + 上下文 dict（proc_map/route_map/wc_map/params），输出结果 dict；
- 参数一律按数值/枚举语义解析（见 consts.PARAM_DEFS 约定）；
- 结果键名与 mps-web 结果结构保持同构（snake_case），便于逐项对照与后续计划消费；
- 下游消费约定：feature_usage 的 missing=True 时不可使用 usage（Task2 置 thr=None、Task4 load 跳过）；
  required_fields 对重复未映射特征不去重（JS 保真）。

与 engine.js 的已知微观差异（均不在业务数据路径上）：
1) nz(" ")：JS Number(" ")=0；本实现 float(" ") 失败 → 返回默认值；
2) feature_usage 遇非数值串：JS 得 usage=NaN/missing=false；本实现返回 missing=True（更安全的收紧）；
3) pick_mode 的 qty 须为数值（JS 隐式转换，Python 会 TypeError）——调用方先 nz。
"""
from __future__ import annotations

import math

from app.mps.consts import FEATURE_FIELDS, FEATURE_MAP


def nz(v, d):
    """空值兜底：None/''/不可解析/NaN → 默认值；否则取 float。"""
    if v is None or v == "":
        return d
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return d if math.isnan(f) else f


def ceil_int(v: float) -> int:
    """向上取整（含 1e-9 容差，避免浮点尾差）。移植自 mps-web ceilInt。"""
    return math.ceil(float(v) - 1e-9)


def urgent_cycle(t: float) -> float:
    """加急压缩：ΔT=IF(T≤5,1, IF(T≤10,2,3))；下限 1 天（CHK-CYCLE-003/004）。"""
    dt = 1 if t <= 5 else 2 if t <= 10 else 3
    return max(t - dt, 1)


def ramp_flux_factor(day_index: float, ramp_days: float) -> float:
    """爬坡期第 t 天有效通量系数 = min(1, t/T)（CHK-CYCLE-008；仅产能校验折算用）。

    暂无调用方：待计划 3（排产解码/产能校验）或计划 5 接入。
    """
    t = nz(ramp_days, 0)
    if t <= 0:
        return 1.0
    return min(1.0, nz(day_index, 0) / t)


def required_fields(code: str, route_rows: list[dict]) -> list[dict]:
    """某套工艺选择后需录入的必填特征项（含未映射特征的原样提示）。"""
    steps = sorted((r for r in route_rows if r["code"] == code), key=lambda r: r["seq"])
    keys: set[str] = set()
    for s in steps:
        for k in FEATURE_MAP.get(s.get("feature") or "", []):
            keys.add(k)
    fields = [dict(f, required=True) for f in FEATURE_FIELDS if f["key"] in keys]
    for s in steps:
        feat = s.get("feature") or ""
        if feat and feat not in FEATURE_MAP:
            fields.append({
                "key": feat, "label": feat, "unit": "", "group": "未映射",
                "required": True, "unmapped": True,
            })
    return fields


def pick_mode(wc: dict | None, qty: float) -> dict | None:
    """生产模式分流（CHK-FLUX-009/010/011）：按订单批量与阈值选半自动/自动。"""
    if not wc or not wc.get("modes"):
        return None
    modes = wc["modes"]
    if len(modes) == 1:
        return {"mode": modes[0], "mode_name": modes[0].get("mode") or "/"}
    threshold = nz(modes[0].get("split_threshold"), 0)
    auto = next(
        (m for m in modes if "自动" in str(m.get("mode", "")) and "半自动" not in str(m.get("mode", ""))),
        modes[1],
    )
    semi = modes[0]
    chosen = semi if qty < threshold else auto
    return {"mode": chosen, "mode_name": chosen.get("mode") or "/"}


def feature_usage(step: dict, feats: dict) -> dict:
    """工序在某产品下的单只特征用量（CHK-FLUX-014 缺参排除）。"""
    mapped = FEATURE_MAP.get(step.get("feature") or "", [])
    if step.get("feature") == "工单产品数量N":
        return {"key": "N", "usage": 1, "missing": False}
    usage_key = mapped[0] if mapped else None
    if not usage_key:
        return {"key": None, "usage": 1, "missing": True}
    usage = feats.get(usage_key)
    if usage is None or usage == "" or nz(usage, 0) <= 0:
        return {"key": usage_key, "usage": None, "missing": True}
    return {"key": usage_key, "usage": nz(usage, 0), "missing": False}


def conv_factor(step: dict, feats: dict, p: dict) -> float:
    """折算系数（CHK-FLUX-006/007/008/017）：DB 按胶水类型数、WB 按引线类型数。"""
    field = step.get("cf_field")
    if not field or field == "/":
        return 1.0
    feature = str(step.get("feature") or "")
    if field == "DB胶水类型Y_die":
        cnt_key = "Y_die2" if feature.endswith("-2") else "Y_die"
        cnt = nz(feats.get(cnt_key), 1) or 1
        return nz(p.get("cf_db_3") if cnt >= 3 else (p.get("cf_db_2") if cnt == 2 else p.get("cf_db_1")), 1.0)
    cnt_key = "Y_wire2" if feature.endswith("-2") else "Y_wire"
    cnt = nz(feats.get(cnt_key), 1) or 1
    return nz(p.get("cf_wb_3") if cnt >= 3 else (p.get("cf_wb_2") if cnt == 2 else p.get("cf_wb_1")), 1.0)
