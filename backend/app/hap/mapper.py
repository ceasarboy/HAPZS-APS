"""HAP 数据与 OpenAPS 实体的映射模块。

负责将 HAP 工作表中的行数据转换为 OpenAPS 求解引擎所需的 DataFrame 格式，
以及将排产结果转换回 HAP 可写入的字段格式。

HAP 特殊规则：
- 选项字段使用 key 而非显示值
- 数值字段读取为字符串，需转换为数值类型
- 关联字段使用 belongsto 类型
"""

import pandas as pd
from loguru import logger


# ── V2 映射函数 ──────────────────────────────────────────────────────────


def map_hap_demand_plans_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 需求计划数据转为 OpenAPS 的 DemandPlan 格式。

    Args:
        hap_rows: HAP 工作表行数据列表，每项包含 rowid 和 fields

    Returns:
        pd.DataFrame: OpenAPS 格式的需求计划数据，包含以下列：
            - dp_code: 需求计划编号
            - dp_quantity: 需求数量
            - dp_unit: 单位
            - dp_due_date: 交付日期
            - dp_priority: 优先级
            - dp_status: 状态
            - dp_product: 关联产品
            - dp_remark: 备注
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "dp_code": str(fields.get("需求计划编号", fields.get("dp_code", ""))),
                "dp_quantity": _parse_numeric_field(fields.get("需求数量", fields.get("dp_quantity", 0))),
                "dp_unit": _parse_option_field(fields.get("单位", fields.get("dp_unit", "台"))),
                "dp_due_date": str(fields.get("交付日期", fields.get("dp_due_date", ""))),
                "dp_priority": _parse_option_field(fields.get("优先级", fields.get("dp_priority", "中"))),
                "dp_status": _parse_option_field(fields.get("状态", fields.get("dp_status", "待确认"))),
                "dp_product": str(fields.get("关联产品", fields.get("dp_product", ""))),
                "dp_remark": str(fields.get("备注", fields.get("dp_remark", ""))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射需求计划行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射需求计划数据完成，共 {} 条", len(df))
    return df


def map_hap_resource_calendar_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 资源日历数据转为 OpenAPS 的 ResourceCalendar 格式。

    Args:
        hap_rows: HAP 资源日历工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的资源日历数据，包含以下列：
            - rc_code: 日历编码
            - rc_date: 日期
            - rc_is_workday: 是否工作日
            - rc_daily_capacity: 日产能
            - rc_efficiency: 效率
            - rc_effective_capacity: 有效产能
            - rc_equipment_count: 设备数
            - rc_worker_count: 人员数
            - rc_line: 关联产线
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "rc_code": str(fields.get("日历编码", fields.get("rc_code", ""))),
                "rc_date": str(fields.get("日期", fields.get("rc_date", ""))),
                "rc_is_workday": _parse_bool_field(fields.get("是否工作日", fields.get("rc_is_workday", True))),
                "rc_daily_capacity": _parse_numeric_field(fields.get("日产能", fields.get("rc_daily_capacity", 0))),
                "rc_efficiency": _parse_numeric_field(fields.get("效率", fields.get("rc_efficiency", 100))),
                "rc_effective_capacity": _parse_numeric_field(fields.get("有效产能", fields.get("rc_effective_capacity", 0))),
                "rc_equipment_count": _parse_numeric_field(fields.get("设备数", fields.get("rc_equipment_count", 0))),
                "rc_worker_count": _parse_numeric_field(fields.get("人员数", fields.get("rc_worker_count", 0))),
                "rc_line": str(fields.get("关联产线", fields.get("rc_line", ""))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射资源日历行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射资源日历数据完成，共 {} 条", len(df))
    return df


def map_hap_production_lines_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 产线数据转为 OpenAPS 的 ProductionLine 格式。

    Args:
        hap_rows: HAP 产线工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的产线数据，包含以下列：
            - line_code: 产线编码
            - line_name: 产线名称
            - line_type: 产线类型
            - line_capacity: 日产能
            - line_load: 负荷率
            - line_efficiency: 效率
            - line_location: 位置
            - line_status: 状态
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "line_code": str(fields.get("产线编码", fields.get("line_code", ""))),
                "line_name": str(fields.get("产线名称", fields.get("line_name", ""))),
                "line_type": _parse_option_field(fields.get("产线类型", fields.get("line_type", "主产线"))),
                "line_capacity": _parse_numeric_field(fields.get("日产能", fields.get("line_capacity", 0))),
                "line_load": _parse_numeric_field(fields.get("负荷率", fields.get("line_load", 0))),
                "line_efficiency": _parse_numeric_field(fields.get("效率", fields.get("line_efficiency", 100))),
                "line_location": str(fields.get("位置", fields.get("line_location", ""))),
                "line_status": _parse_option_field(fields.get("状态", fields.get("line_status", "运行中"))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射产线行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射产线数据完成，共 {} 条", len(df))
    return df


def map_hap_process_info_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 工序信息数据转为 OpenAPS 的 ProcessInfo 格式。

    Args:
        hap_rows: HAP 工序信息工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的工序信息数据
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "proc_code": str(fields.get("工序编码", fields.get("proc_code", ""))),
                "proc_name": str(fields.get("工序名称", fields.get("proc_name", ""))),
                "proc_type": _parse_option_field(fields.get("工序类型", fields.get("proc_type", ""))),
                "constraint_type": _parse_option_field(fields.get("约束类型", fields.get("constraint_type", ""))),
                "cycle_time": _parse_numeric_field(fields.get("标准节拍", fields.get("cycle_time", 0))),
                "setup_time": _parse_numeric_field(fields.get("换型时间", fields.get("setup_time", 0))),
                "wait_time": _parse_numeric_field(fields.get("等待时间", fields.get("wait_time", 0))),
                "wait_includes_offhours": _parse_bool_field(fields.get("等待计入下班时间", fields.get("wait_includes_offhours", True))),
                "prep_time": _parse_numeric_field(fields.get("准备时间", fields.get("prep_time", 0))),
                "is_qc_point": _parse_bool_field(fields.get("是否质检点", fields.get("is_qc_point", False))),
                "status": _parse_option_field(fields.get("状态", fields.get("status", "启用"))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射工序信息行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射工序信息数据完成，共 {} 条", len(df))
    return df


def map_hap_product_process_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 产品工艺数据转为 OpenAPS 的 ProductProcess 格式。

    Args:
        hap_rows: HAP 产品工艺工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的产品工艺数据
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "product_id": str(fields.get("关联产品", fields.get("product_id", ""))),
                "process_id": str(fields.get("关联工序", fields.get("process_id", ""))),
                "seq": _parse_numeric_field(fields.get("工序顺序", fields.get("seq", 0))),
                "std_time": _parse_numeric_field(fields.get("标准工时", fields.get("std_time", 0))),
                "dependency_type": _parse_option_field(fields.get("依赖类型", fields.get("dependency_type", "FS"))),
                "is_key": _parse_bool_field(fields.get("是否关键工序", fields.get("is_key", False))),
                "remark": str(fields.get("备注", fields.get("remark", ""))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射产品工艺行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射产品工艺数据完成，共 {} 条", len(df))
    return df


def map_hap_line_process_config_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 产线工艺配置数据转为 OpenAPS 的 LineProcessConfig 格式。

    Args:
        hap_rows: HAP 产线工艺配置工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的产线工艺配置数据
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "line_id": str(fields.get("关联产线", fields.get("line_id", ""))),
                "process_id": str(fields.get("关联工序", fields.get("process_id", ""))),
                "daily_capacity": _parse_numeric_field(fields.get("日产能", fields.get("daily_capacity", 0))),
                "efficiency": _parse_numeric_field(fields.get("效率", fields.get("efficiency", 100))),
                "min_batch": _parse_numeric_field(fields.get("最小批量", fields.get("min_batch", 0))),
                "is_bottleneck": _parse_bool_field(fields.get("是否瓶颈", fields.get("is_bottleneck", False))),
                "equipment_count": _parse_numeric_field(fields.get("设备数", fields.get("equipment_count", 0))),
                "worker_count": _parse_numeric_field(fields.get("人员数", fields.get("worker_count", 0))),
                "status": _parse_option_field(fields.get("状态", fields.get("status", "启用"))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射产线工艺配置行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射产线工艺配置数据完成，共 {} 条", len(df))
    return df


def map_hap_process_bom_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 工序 BOM 数据转为 OpenAPS 的 ProcessBOM 格式。

    Args:
        hap_rows: HAP 工序 BOM 工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的工序 BOM 数据
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "product_id": str(fields.get("关联产品", fields.get("product_id", ""))),
                "process_id": str(fields.get("关联工序", fields.get("process_id", ""))),
                "material_id": str(fields.get("关联物料", fields.get("material_id", ""))),
                "unit_qty": _parse_numeric_field(fields.get("单位用量", fields.get("unit_qty", 0))),
                "reusable": _parse_bool_field(fields.get("是否可复用", fields.get("reusable", False))),
                "remark": str(fields.get("备注", fields.get("remark", ""))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射工序 BOM 行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射工序 BOM 数据完成，共 {} 条", len(df))
    return df


def map_hap_material_kitting_to_dataframe(hap_rows: list[dict]) -> pd.DataFrame:
    """将 HAP 物料齐套数据转为 OpenAPS 的 MaterialKitting 格式。

    Args:
        hap_rows: HAP 物料齐套工作表行数据列表

    Returns:
        pd.DataFrame: OpenAPS 格式的物料齐套数据
    """
    records = []
    for row in hap_rows:
        fields = row.get("fields", row)
        try:
            record = {
                "demand_id": str(fields.get("关联需求计划", fields.get("demand_id", ""))),
                "product_id": str(fields.get("关联产品", fields.get("product_id", ""))),
                "process_id": str(fields.get("关联工序", fields.get("process_id", ""))),
                "material_id": str(fields.get("关联物料", fields.get("material_id", ""))),
                "required_qty": _parse_numeric_field(fields.get("需求数量", fields.get("required_qty", 0))),
                "available_qty": _parse_numeric_field(fields.get("可用数量", fields.get("available_qty", 0))),
                "shortage_qty": _parse_numeric_field(fields.get("缺料数量", fields.get("shortage_qty", 0))),
                "kitting_date": str(fields.get("齐套日期", fields.get("kitting_date", ""))),
                "kitting_status": _parse_option_field(fields.get("齐套状态", fields.get("kitting_status", "待确认"))),
            }
            records.append(record)
        except Exception as e:
            logger.warning("映射物料齐套行数据失败，rowid: {}, 错误: {}", row.get("rowid", ""), e)
            continue

    df = pd.DataFrame(records)
    logger.info("映射物料齐套数据完成，共 {} 条", len(df))
    return df


# ── 结果映射 ─────────────────────────────────────────────────────────────


def map_result_to_hap_fields(
    result_df: pd.DataFrame,
    worksheet_structure: dict,
) -> list[dict]:
    """将排产结果转为 HAP 写入格式。

    需要根据 worksheet_structure 中的字段定义，将 DataFrame 列映射到 HAP 字段 controlId。
    选项字段需转换为 key 值，数值字段需转换为字符串。

    V2 新增字段映射：sr_code, sr_seq, sr_demand, sr_product, sr_line, sr_process

    Args:
        result_df: 排产结果 DataFrame
        worksheet_structure: HAP 工作表结构信息，包含字段定义

    Returns:
        list[dict]: HAP 行数据列表，每项为 {controlId: value} 格式
    """
    hap_rows = []
    fields_map = _build_fields_map(worksheet_structure)

    # V2 字段名映射：OpenAPS 列名 → HAP 字段名
    v2_field_aliases = {
        "sr_code": "排产结果编号",
        "sr_seq": "工序顺序",
        "sr_demand": "关联需求计划",
        "sr_product": "关联产品",
        "sr_line": "关联产线",
        "sr_process": "关联工序",
    }

    for _, row in result_df.iterrows():
        hap_fields = {}
        for col_name, value in row.items():
            # 先尝试直接匹配，再尝试 V2 别名匹配
            control_id = fields_map.get(col_name)
            if not control_id:
                hap_field_name = v2_field_aliases.get(col_name, "")
                if hap_field_name:
                    control_id = fields_map.get(hap_field_name)
            if not control_id:
                continue
            # 选项字段需转换为 key
            if _is_option_field(col_name, worksheet_structure):
                hap_fields[control_id] = str(value)
            # 数值字段需转换为字符串
            elif isinstance(value, (int, float)):
                hap_fields[control_id] = str(value)
            else:
                hap_fields[control_id] = str(value)
        hap_rows.append(hap_fields)

    logger.info("映射排产结果到 HAP 格式完成，共 {} 行", len(hap_rows))
    return hap_rows


# ── V1 兼容别名 ──────────────────────────────────────────────────────────

map_hap_orders_to_dataframe = map_hap_demand_plans_to_dataframe
map_hap_calendar_to_dataframe = map_hap_resource_calendar_to_dataframe
map_hap_workcenters_to_dataframe = map_hap_production_lines_to_dataframe


# ── 内部工具函数 ──────────────────────────────────────────────────────────


def _parse_numeric_field(value: object) -> float:
    """将 HAP 数值字段（可能为字符串）转换为 float。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return 0.0
    return 0.0


def _parse_option_field(value: object) -> str:
    """解析 HAP 选项字段，提取显示值。

    HAP 选项字段可能返回 {"key": "xxx", "value": "显示值"} 格式，
    也可能直接返回字符串。
    """
    if isinstance(value, dict):
        return str(value.get("value", value.get("key", "")))
    return str(value) if value else ""


def _parse_bool_field(value: object) -> bool:
    """将 HAP 布尔字段转换为 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "是", "yes")
    if isinstance(value, dict):
        return str(value.get("key", value.get("value", ""))).lower() in ("true", "1", "是", "yes")
    return False


def _build_fields_map(worksheet_structure: dict) -> dict[str, str]:
    """根据工作表结构构建 列名→controlId 映射。"""
    fields_map = {}
    controls = worksheet_structure.get("data", {}).get("controls", [])
    for control in controls:
        control_id = control.get("controlId", "")
        control_name = control.get("controlName", "")
        if control_id and control_name:
            fields_map[control_name] = control_id
    return fields_map


def _is_option_field(col_name: str, worksheet_structure: dict) -> bool:
    """判断字段是否为选项类型。"""
    controls = worksheet_structure.get("data", {}).get("controls", [])
    for control in controls:
        if control.get("controlName") == col_name:
            # HAP 选项字段类型: 10=单选, 11=多选
            return control.get("type") in (10, 11)
    return False
