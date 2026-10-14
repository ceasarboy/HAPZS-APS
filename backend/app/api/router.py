"""API 路由注册模块，汇总所有 v1 版本路由。"""

from fastapi import APIRouter

from app.api.v1 import changeover, config, hap, report_work, result, schedule, sync, work_time
from app.api.v1.crud import create_crud_router
from app.models.entities import (
    Product, ProcessInfo, ProductionLine, ProductProcess, LineProcessConfig,
    MaterialMaster, ProcessBOM, MaterialKitting, DemandPlan, ScheduleResult,
    ResourceCalendar, ChangeoverMatrix, BufferConfig, SchedulePlan, ReportWorkOrder,
    ProcessScheduleOrder,
)
from app.schemas.entities import (
    ProductCreate, ProductUpdate, ProductOut,
    ProcessInfoCreate, ProcessInfoUpdate, ProcessInfoOut,
    ProductionLineCreate, ProductionLineUpdate, ProductionLineOut,
    ProductProcessCreate, ProductProcessUpdate, ProductProcessOut,
    LineProcessConfigCreate, LineProcessConfigUpdate, LineProcessConfigOut,
    MaterialMasterCreate, MaterialMasterUpdate, MaterialMasterOut,
    ProcessBOMCreate, ProcessBOMUpdate, ProcessBOMOut,
    MaterialKittingCreate, MaterialKittingUpdate, MaterialKittingOut,
    DemandPlanCreate, DemandPlanUpdate, DemandPlanOut,
    ScheduleResultCreate, ScheduleResultUpdate, ScheduleResultOut,
    ResourceCalendarCreate, ResourceCalendarUpdate, ResourceCalendarOut,
    ChangeoverMatrixCreate, ChangeoverMatrixUpdate, ChangeoverMatrixOut,
    BufferConfigCreate, BufferConfigUpdate, BufferConfigOut,
    SchedulePlanCreate, SchedulePlanUpdate, SchedulePlanOut,
    ReportWorkOrderCreate, ReportWorkOrderUpdate, ReportWorkOrderOut,
    ProcessScheduleOrderCreate, ProcessScheduleOrderUpdate, ProcessScheduleOrderOut,
)

# 创建 v1 版本路由器
v1_router = APIRouter(prefix="/api/v1")

# 注册各子模块路由
v1_router.include_router(hap.router, prefix="/hap", tags=["HAP 数据代理"])
v1_router.include_router(schedule.router, prefix="/schedule", tags=["排产任务"])
v1_router.include_router(result.router, prefix="/result", tags=["排产结果"])
v1_router.include_router(changeover.router, prefix="/changeover", tags=["换线矩阵"])
v1_router.include_router(config.router, prefix="/config", tags=["系统配置"])
v1_router.include_router(sync.router, prefix="/sync", tags=["HAP 同步"])
v1_router.include_router(report_work.router, prefix="/report-work", tags=["报工管理"])
v1_router.include_router(work_time.router, tags=["工作时间模式"])

# ── V3: 14张业务表 CRUD 路由 ──────────────────────────────────────────────
v1_router.include_router(
    create_crud_router(Product, ProductCreate, ProductUpdate, ProductOut, "/products", ["产品管理"]),
    prefix="/products", tags=["产品管理"],
)
v1_router.include_router(
    create_crud_router(ProcessInfo, ProcessInfoCreate, ProcessInfoUpdate, ProcessInfoOut, "/process_info", ["工序管理"]),
    prefix="/process-info", tags=["工序管理"],
)
v1_router.include_router(
    create_crud_router(ProductionLine, ProductionLineCreate, ProductionLineUpdate, ProductionLineOut, "/production_lines", ["产线管理"]),
    prefix="/production-lines", tags=["产线管理"],
)
v1_router.include_router(
    create_crud_router(ProductProcess, ProductProcessCreate, ProductProcessUpdate, ProductProcessOut, "/product_processes", ["产品工艺"]),
    prefix="/product-processes", tags=["产品工艺"],
)
v1_router.include_router(
    create_crud_router(LineProcessConfig, LineProcessConfigCreate, LineProcessConfigUpdate, LineProcessConfigOut, "/line_process_configs", ["产线工艺配置"]),
    prefix="/line-process-configs", tags=["产线工艺配置"],
)
v1_router.include_router(
    create_crud_router(MaterialMaster, MaterialMasterCreate, MaterialMasterUpdate, MaterialMasterOut, "/material_masters", ["物料管理"]),
    prefix="/material-masters", tags=["物料管理"],
)
v1_router.include_router(
    create_crud_router(ProcessBOM, ProcessBOMCreate, ProcessBOMUpdate, ProcessBOMOut, "/process_boms", ["工序BOM"]),
    prefix="/process-boms", tags=["工序BOM"],
)
v1_router.include_router(
    create_crud_router(MaterialKitting, MaterialKittingCreate, MaterialKittingUpdate, MaterialKittingOut, "/material_kittings", ["物料齐套"]),
    prefix="/material-kittings", tags=["物料齐套"],
)
v1_router.include_router(
    create_crud_router(DemandPlan, DemandPlanCreate, DemandPlanUpdate, DemandPlanOut, "/demand_plans", ["需求计划"]),
    prefix="/demand-plans", tags=["需求计划"],
)
v1_router.include_router(
    create_crud_router(ScheduleResult, ScheduleResultCreate, ScheduleResultUpdate, ScheduleResultOut, "/schedule_results", ["排产结果"]),
    prefix="/schedule-results", tags=["排产结果"],
)
v1_router.include_router(
    create_crud_router(ResourceCalendar, ResourceCalendarCreate, ResourceCalendarUpdate, ResourceCalendarOut, "/resource_calendars", ["资源日历"]),
    prefix="/resource-calendars", tags=["资源日历"],
)
v1_router.include_router(
    create_crud_router(ChangeoverMatrix, ChangeoverMatrixCreate, ChangeoverMatrixUpdate, ChangeoverMatrixOut, "/changeover_matrices", ["换线矩阵"]),
    prefix="/changeover-matrices", tags=["换线矩阵"],
)
v1_router.include_router(
    create_crud_router(BufferConfig, BufferConfigCreate, BufferConfigUpdate, BufferConfigOut, "/buffer_configs", ["缓冲配置"]),
    prefix="/buffer-configs", tags=["缓冲配置"],
)
v1_router.include_router(
    create_crud_router(SchedulePlan, SchedulePlanCreate, SchedulePlanUpdate, SchedulePlanOut, "/schedule_plans", ["排产方案"]),
    prefix="/schedule-plans", tags=["排产方案"],
)
v1_router.include_router(
    create_crud_router(ReportWorkOrder, ReportWorkOrderCreate, ReportWorkOrderUpdate, ReportWorkOrderOut, "/report_work_orders", ["报工工单"]),
    prefix="/report-work-orders", tags=["报工工单"],
)
v1_router.include_router(
    create_crud_router(ProcessScheduleOrder, ProcessScheduleOrderCreate, ProcessScheduleOrderUpdate, ProcessScheduleOrderOut, "/process_schedule_orders", ["工序排产单"]),
    prefix="/process-schedule-orders", tags=["工序排产单"],
)
