"""HAP 数据服务，封装 HAP 客户端调用和数据转换逻辑。"""

from loguru import logger

from app.hap.client import HAPClient
from app.hap.mapper import (
    map_hap_demand_plans_to_dataframe,
    map_hap_material_kitting_to_dataframe,
    map_hap_process_bom_to_dataframe,
    map_hap_process_info_to_dataframe,
    map_hap_product_process_to_dataframe,
    map_hap_line_process_config_to_dataframe,
    map_hap_production_lines_to_dataframe,
    map_hap_resource_calendar_to_dataframe,
)
from app.schemas.hap import (
    DemandPlanItem,
    MaterialKittingItem,
    ProcessBOMItem,
    ProcessInfoItem,
    ProductProcessItem,
    LineProcessConfigItem,
    ProductionLineItem,
    ResourceCalendarItem,
)


class HAPService:
    """HAP 数据服务，提供数据拉取、转换和回写能力。"""

    # 工作表 ID 映射（V2）
    WORKSHEET_IDS: dict[str, str] = {
        "demand_plan": "demand_plan_worksheet_id",
        "resource_calendar": "resource_calendar_worksheet_id",
        "production_line": "production_line_worksheet_id",
        "material_kitting": "material_kitting_worksheet_id",
        "process_info": "process_info_worksheet_id",
        "product_process": "product_process_worksheet_id",
        "line_process_config": "line_process_config_worksheet_id",
        "process_bom": "process_bom_worksheet_id",
    }

    def __init__(self) -> None:
        """初始化 HAP 服务，创建 HAP 客户端实例。"""
        self.client = HAPClient()

    async def fetch_demand_plans(self, status: str | None = None) -> list[DemandPlanItem]:
        """从 HAP 拉取需求计划数据并转换为 DemandPlanItem 列表。

        Args:
            status: 需求计划状态筛选条件

        Returns:
            list[DemandPlanItem]: 需求计划数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("demand_plan", "")

        # 构建筛选条件
        filters = None
        if status:
            filters = [{"controlId": "dp_status_field_id", "filterType": 2, "value": status}]

        # 拉取数据
        response = await self.client.get_rows(
            worksheet_id=worksheet_id,
            filter=filters,
        )
        rows = response.get("data", {}).get("rows", [])

        # 转换为 DataFrame 再转为 DemandPlanItem
        df = map_hap_demand_plans_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(DemandPlanItem(
                dp_code=row.get("dp_code", ""),
                dp_quantity=float(row.get("dp_quantity", 0)),
                dp_unit=row.get("dp_unit", "台"),
                dp_due_date=row.get("dp_due_date", ""),
                dp_priority=row.get("dp_priority", "中"),
                dp_status=row.get("dp_status", "待确认"),
                dp_product=row.get("dp_product", ""),
                dp_remark=row.get("dp_remark", ""),
            ))

        logger.info("拉取需求计划数据完成，共 {} 条", len(items))
        return items

    async def fetch_resource_calendar(self) -> list[ResourceCalendarItem]:
        """从 HAP 拉取资源日历数据并转换为 ResourceCalendarItem 列表。

        Returns:
            list[ResourceCalendarItem]: 资源日历数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("resource_calendar", "")

        # 分页拉取全部数据（HAP 单次最多返回1000条，资源日历可能超过3000条）
        all_rows: list[dict] = []
        page_index = 1
        while True:
            response = await self.client.get_rows(
                worksheet_id=worksheet_id,
                page_index=page_index,
                page_size=1000,
            )
            rows = response.get("data", {}).get("rows", [])
            all_rows.extend(rows)
            total = int(response.get("data", {}).get("total", 0))
            if len(all_rows) >= total or not rows:
                break
            page_index += 1

        df = map_hap_resource_calendar_to_dataframe(all_rows)
        items = []
        for _, row in df.iterrows():
            items.append(ResourceCalendarItem(
                rc_code=row.get("rc_code", ""),
                rc_date=row.get("rc_date", ""),
                rc_is_workday=bool(row.get("rc_is_workday", True)),
                rc_daily_capacity=int(row.get("rc_daily_capacity", 0)),
                rc_efficiency=float(row.get("rc_efficiency", 100)),
                rc_effective_capacity=float(row.get("rc_effective_capacity", 0)),
                rc_equipment_count=int(row.get("rc_equipment_count", 0)),
                rc_worker_count=int(row.get("rc_worker_count", 0)),
                rc_line=row.get("rc_line", ""),
            ))

        logger.info("拉取资源日历数据完成，共 {} 条", len(items))
        return items

    async def fetch_production_lines(self) -> list[ProductionLineItem]:
        """从 HAP 拉取产线数据并转换为 ProductionLineItem 列表。

        Returns:
            list[ProductionLineItem]: 产线数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("production_line", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_production_lines_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(ProductionLineItem(
                line_code=row.get("line_code", ""),
                line_name=row.get("line_name", ""),
                line_type=row.get("line_type", "主产线"),
                line_capacity=int(row.get("line_capacity", 0)),
                line_load=float(row.get("line_load", 0)),
                line_efficiency=float(row.get("line_efficiency", 100)),
                line_location=row.get("line_location", ""),
                line_status=row.get("line_status", "运行中"),
            ))

        logger.info("拉取产线数据完成，共 {} 条", len(items))
        return items

    async def fetch_material_kitting(self) -> list[MaterialKittingItem]:
        """从 HAP 拉取物料齐套数据并转换为 MaterialKittingItem 列表。

        Returns:
            list[MaterialKittingItem]: 物料齐套数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("material_kitting", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_material_kitting_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(MaterialKittingItem(
                demand_id=row.get("demand_id", ""),
                product_id=row.get("product_id", ""),
                process_id=row.get("process_id", ""),
                material_id=row.get("material_id", ""),
                required_qty=int(row.get("required_qty", 0)),
                available_qty=int(row.get("available_qty", 0)),
                shortage_qty=int(row.get("shortage_qty", 0)),
                kitting_date=row.get("kitting_date", ""),
                kitting_status=row.get("kitting_status", "待确认"),
            ))

        logger.info("拉取物料齐套数据完成，共 {} 条", len(items))
        return items

    async def fetch_process_info(self) -> list[ProcessInfoItem]:
        """从 HAP 拉取工序信息数据并转换为 ProcessInfoItem 列表。

        Returns:
            list[ProcessInfoItem]: 工序信息数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("process_info", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_process_info_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(ProcessInfoItem(
                proc_code=row.get("proc_code", ""),
                proc_name=row.get("proc_name", ""),
                proc_type=row.get("proc_type", ""),
                constraint_type=row.get("constraint_type", ""),
                cycle_time=float(row.get("cycle_time", 0)),
                setup_time=float(row.get("setup_time", 0)),
                is_qc_point=bool(row.get("is_qc_point", False)),
                status=row.get("status", "启用"),
            ))

        logger.info("拉取工序信息数据完成，共 {} 条", len(items))
        return items

    async def fetch_product_processes(self) -> list[ProductProcessItem]:
        """从 HAP 拉取产品工艺数据并转换为 ProductProcessItem 列表。

        Returns:
            list[ProductProcessItem]: 产品工艺数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("product_process", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_product_process_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(ProductProcessItem(
                product_id=row.get("product_id", ""),
                process_id=row.get("process_id", ""),
                seq=int(row.get("seq", 0)),
                std_time=float(row.get("std_time", 0)),
                is_key=bool(row.get("is_key", False)),
                remark=row.get("remark", ""),
            ))

        logger.info("拉取产品工艺数据完成，共 {} 条", len(items))
        return items

    async def fetch_line_process_configs(self) -> list[LineProcessConfigItem]:
        """从 HAP 拉取产线工艺配置数据并转换为 LineProcessConfigItem 列表。

        Returns:
            list[LineProcessConfigItem]: 产线工艺配置数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("line_process_config", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_line_process_config_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(LineProcessConfigItem(
                line_id=row.get("line_id", ""),
                process_id=row.get("process_id", ""),
                daily_capacity=int(row.get("daily_capacity", 0)),
                efficiency=float(row.get("efficiency", 100)),
                min_batch=int(row.get("min_batch", 0)),
                is_bottleneck=bool(row.get("is_bottleneck", False)),
                equipment_count=int(row.get("equipment_count", 0)),
                worker_count=int(row.get("worker_count", 0)),
                status=row.get("status", "启用"),
            ))

        logger.info("拉取产线工艺配置数据完成，共 {} 条", len(items))
        return items

    async def fetch_process_bom(self) -> list[ProcessBOMItem]:
        """从 HAP 拉取工序 BOM 数据并转换为 ProcessBOMItem 列表。

        Returns:
            list[ProcessBOMItem]: 工序 BOM 数据列表
        """
        worksheet_id = self.WORKSHEET_IDS.get("process_bom", "")

        response = await self.client.get_rows(worksheet_id=worksheet_id)
        rows = response.get("data", {}).get("rows", [])

        df = map_hap_process_bom_to_dataframe(rows)
        items = []
        for _, row in df.iterrows():
            items.append(ProcessBOMItem(
                product_id=row.get("product_id", ""),
                process_id=row.get("process_id", ""),
                material_id=row.get("material_id", ""),
                unit_qty=float(row.get("unit_qty", 0)),
                reusable=bool(row.get("reusable", False)),
                remark=row.get("remark", ""),
            ))

        logger.info("拉取工序 BOM 数据完成，共 {} 条", len(items))
        return items

    async def push_results(self, task_id: str) -> None:
        """将排产结果批量写入 HAP。

        Args:
            task_id: 排产任务 ID
        """
        # TODO: 实现结果回写逻辑
        logger.info("排产结果回写 HAP，task_id: {}", task_id)

    async def sync_all(self) -> dict[str, int]:
        """全量数据同步，拉取所有 HAP 数据并更新本地缓存。

        Returns:
            dict: 各数据类型的同步数量
        """
        demand_plans = await self.fetch_demand_plans()
        resource_calendar = await self.fetch_resource_calendar()
        production_lines = await self.fetch_production_lines()
        material_kitting = await self.fetch_material_kitting()
        process_info = await self.fetch_process_info()
        product_processes = await self.fetch_product_processes()
        line_process_configs = await self.fetch_line_process_configs()
        process_bom = await self.fetch_process_bom()

        result = {
            "demand_plans": len(demand_plans),
            "resource_calendar": len(resource_calendar),
            "production_lines": len(production_lines),
            "material_kitting": len(material_kitting),
            "process_info": len(process_info),
            "product_processes": len(product_processes),
            "line_process_configs": len(line_process_configs),
            "process_bom": len(process_bom),
        }
        logger.info("全量数据同步完成: {}", result)
        return result

    # ── V1 兼容方法 ──────────────────────────────────────────────────────

    async def fetch_orders(self, status: str | None = None) -> list[DemandPlanItem]:
        """V1 兼容：拉取订单数据（实际调用 fetch_demand_plans）。"""
        return await self.fetch_demand_plans(status=status)

    async def fetch_calendar(self) -> list[ResourceCalendarItem]:
        """V1 兼容：拉取日历数据（实际调用 fetch_resource_calendar）。"""
        return await self.fetch_resource_calendar()

    async def fetch_workcenters(self) -> list[ProductionLineItem]:
        """V1 兼容：拉取工作中心数据（实际调用 fetch_production_lines）。"""
        return await self.fetch_production_lines()

    async def fetch_kitting(self) -> list[MaterialKittingItem]:
        """V1 兼容：拉取齐套数据（实际调用 fetch_material_kitting）。"""
        return await self.fetch_material_kitting()
