"""内核上下文装载：数据库 → 内核输入 dict（proc_map/route_map/wc_map/params）。

参数解析遵循 consts 约定：数值键转数值（非法值/缺失回退 PARAM_DEFS 默认值），枚举键保留字符串。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.consts import PARAM_DEFS
from app.mps.kernel import nz

_NUMERIC_PARAM_KEYS = (
    "week_days", "peak_factor", "exclude_braze_yield",
    "cf_db_1", "cf_db_2", "cf_db_3", "cf_wb_1", "cf_wb_2", "cf_wb_3",
    "vapor_cap_cut", "order_buffer_days", "reference_batch", "wb_auto_flux_override",
    "ga_population", "ga_generations", "ga_seed",
)

_PARAM_DEFAULTS = {d["key"]: d["value"] for d in PARAM_DEFS}


async def load_params(session: AsyncSession) -> dict:
    """系统参数：数值键转数值（非法/缺失回退 PARAM_DEFS 默认），枚举键保留字符串。"""
    rows = (await session.execute(select(SystemParam))).scalars().all()
    params: dict = {}
    for row in rows:
        key = row.key
        if key in _NUMERIC_PARAM_KEYS:
            params[key] = nz(row.value, nz(_PARAM_DEFAULTS.get(key), 0))
        else:
            params[key] = row.value
    return params


async def load_ctx(session: AsyncSession) -> dict:
    """装载核算上下文：成套工艺 / 路线 / 工序主数据 / 参数。"""
    proc_map = {p.code: _proc_dict(p) for p in (await session.execute(select(ProcessSet))).scalars().all()}

    route_map: dict[str, list[dict]] = {}
    for r in (await session.execute(select(ProcessRoute))).scalars().all():
        route_map.setdefault(r.code, []).append(_route_dict(r))

    wc_map: dict[str, dict] = {}
    for w in (await session.execute(select(ProcessMaster))).scalars().all():
        key = f"{w.level}|{w.op}"
        wc_map.setdefault(key, {"modes": []})["modes"].append(_wc_mode_dict(w))

    return {"proc_map": proc_map, "route_map": route_map, "wc_map": wc_map,
            "params": await load_params(session)}


def _proc_dict(p: ProcessSet) -> dict:
    return {"code": p.code, "name": p.name, "arch": p.arch, "owner": p.owner,
            "subpart_mode": p.subpart_mode, "subpart_cycle": p.subpart_cycle,
            "ramp_days": p.ramp_days, "yield_ref": p.yield_ref, "cycle_ref": p.cycle_ref,
            "urgent_ref": p.urgent_ref, "ratio_ref": p.ratio_ref, "route_text": p.route_text}


def _route_dict(r: ProcessRoute) -> dict:
    return {"code": r.code, "seq": r.seq, "step_raw": r.step_raw, "step_std": r.step_std,
            "level": r.level, "cycle": r.cycle, "yield_inspect": r.yield_inspect,
            "yield_overall": r.yield_overall, "feature": r.feature,
            "cf_field": r.cf_field, "cf_trigger": r.cf_trigger}


def _wc_mode_dict(w: ProcessMaster) -> dict:
    return {"mode": w.mode, "cycle": w.cycle, "flux_base": w.flux_base, "flux_peak": w.flux_peak,
            "unit": w.unit, "feature": w.feature, "split_threshold": w.split_threshold}
