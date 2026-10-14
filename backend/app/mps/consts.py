"""MPS 业务常量（移植自 mps-web src/consts.js，只读参照，不得改动源文件）。"""

FEATURE_FIELDS: list[dict] = [
    {"key": "N_b", "label": "N_b/单只植球数", "unit": "颗", "group": "芯片级"},
    {"key": "N_fc", "label": "N_fc/单只倒装元件数", "unit": "只", "group": "芯片级"},
    {"key": "N_smt", "label": "N_smt/单只贴装元件数", "unit": "只", "group": "通用"},
    {"key": "N_die", "label": "N_die/单只芯片数", "unit": "只", "group": "通用"},
    {"key": "Y_die", "label": "DB/胶水类型数", "unit": "种", "group": "通用"},
    {"key": "N_wire", "label": "N_wire/单只键合根丝数", "unit": "根", "group": "通用"},
    {"key": "Y_wire", "label": "WB/引线类型数", "unit": "种", "group": "通用"},
    {"key": "N_die2", "label": "N_die-2/第2组芯片数", "unit": "只", "group": "第2组"},
    {"key": "Y_die2", "label": "DB/第2组胶水类型数", "unit": "种", "group": "第2组"},
    {"key": "N_wire2", "label": "N_wire-2/第2组键合根丝数", "unit": "根", "group": "第2组"},
    {"key": "Y_wire2", "label": "WB/第2组引线类型数", "unit": "种", "group": "第2组"},
    {"key": "N_bs", "label": "N_bs/单只钎焊部件数", "unit": "只", "group": "组件级"},
    {"key": "N_a", "label": "N_a/单只电装点数(焊点+螺钉)", "unit": "点", "group": "组件级"},
]

FEATURE_MAP: dict[str, list[str]] = {
    "植球-球数N_b": ["N_b"],
    "FC-倒装元件数N_fc": ["N_fc"],
    "钎焊-部件数N_bs": ["N_bs"],
    "SMT-贴装元件数N_smt": ["N_smt"],
    "DB-芯片数N_die": ["N_die", "Y_die"],
    "DB-芯片数N_die-1": ["N_die", "Y_die"],
    "DB-芯片数N_die-2": ["N_die2", "Y_die2"],
    "WB-键合线数N_wire": ["N_wire", "Y_wire"],
    "WB-键合线数N_wire-1": ["N_wire", "Y_wire"],
    "WB-键合线数N_wire-2": ["N_wire2", "Y_wire2"],
    "电装-（焊点+螺钉）数量N_a": ["N_a"],
    "工单产品数量N": [],
}

# 参数定义（11 项来自 mps-web PARAM_DEFS 核心组；后 4 项为本系统新增/疑点开关）。
# 有意延后：mps-web 另有 7 项"排产约束"组参数（day_cap_mode/day_cap_ratio/takt_window/
# op_lag_days/takt_max_gap/balance_level/missing_reserve_ratio，仅其未接入的 balance.js 使用），
# 待计划 3 确定均衡/节拍策略时按需补入，并同步参数页（评审记录 2026-10-14）。
# 参数消费约定：一律按数值/枚举语义解析（int/float/enum），禁止按字符串字面量精确比较
# （种子值可能是 "1.0"、默认值可能是 "1"，二者数值等价）。
PARAM_DEFS: list[dict] = [
    {"key": "week_days", "value": "6", "label": "周工作天数", "group": "排产", "hint": "周负荷可用产能 = 基准通量 × 周工作天数"},
    {"key": "peak_factor", "value": "1.1", "label": "峰值系数", "group": "排产", "hint": "基准峰值通量 = 基准均值通量 × 峰值系数"},
    {"key": "use_peak", "value": "mean", "label": "通量口径", "group": "排产", "hint": "mean=基准均值通量 / peak=基准峰值通量"},
    {"key": "exclude_braze_yield", "value": "1", "label": "组件级放量比剔除钎焊良率", "group": "成品率", "hint": "1=组件级(C系列)放量比不计入钎焊工序综合成品率"},
    {"key": "cf_db_1", "value": "1", "label": "DB胶水类型数=1 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_db_2", "value": "0.9", "label": "DB胶水类型数=2 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_db_3", "value": "0.8", "label": "DB胶水类型数≥3 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_1", "value": "1", "label": "WB引线类型数=1 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_2", "value": "0.95", "label": "WB引线类型数=2 折算系数", "group": "折算系数", "hint": ""},
    {"key": "cf_wb_3", "value": "0.9", "label": "WB引线类型数≥3 折算系数", "group": "折算系数", "hint": ""},
    {"key": "vapor_cap_cut", "value": "1", "label": "无水汽时封盖工序周期", "group": "周期", "hint": "封盖类工序基准周期在无水汽含量要求时压缩到该值"},
    {"key": "order_buffer_days", "value": "1", "label": "订单缓冲（天）", "group": "交付", "hint": "交付周期 = 批量周期 + 爬坡 + 订单缓冲；疑点：mps-web 未计入，待业务确认"},
    {"key": "reference_batch", "value": "1000", "label": "参考批量（只）", "group": "分流", "hint": "基准通量的分流判定批量；周负荷按订单实际批量动态分流"},
    {"key": "wb_auto_flux_override", "value": "0", "label": "模块级自动WB通量覆盖", "group": "分流", "hint": "根丝/天；0=使用主数据通量；疑点①：逻辑书12000 vs 主数据口径20000，双档测试用 12000/20000"},
    {"key": "round_mode", "value": "exact", "label": "批量项取整口径", "group": "交付", "hint": "exact=V1.6也算例不取整 / ceil=向上取整；疑点待业务确认"},
    {"key": "ramp_trigger", "value": "first_flag", "label": "爬坡触发口径", "group": "爬坡", "hint": "first_flag=首单/复线/变更首件触发 / all=所有订单；疑点待业务确认"},
]
