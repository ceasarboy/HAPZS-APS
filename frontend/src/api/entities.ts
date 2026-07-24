/** 15张业务表的 CRUD API 实例 */

import { createCrudApi } from './crud';
import type {
  Product, ProductCreate, ProductUpdate,
  ProcessInfo, ProcessInfoCreate, ProcessInfoUpdate,
  ProductionLine, ProductionLineCreate, ProductionLineUpdate,
  ProductProcess, ProductProcessCreate, ProductProcessUpdate,
  LineProcessConfig, LineProcessConfigCreate, LineProcessConfigUpdate,
  MaterialMaster, MaterialMasterCreate, MaterialMasterUpdate,
  ProcessBOM, ProcessBOMCreate, ProcessBOMUpdate,
  MaterialKitting, MaterialKittingCreate, MaterialKittingUpdate,
  DemandPlan, DemandPlanCreate, DemandPlanUpdate,
  ScheduleResult, ScheduleResultCreate, ScheduleResultUpdate,
  ResourceCalendar, ResourceCalendarCreate, ResourceCalendarUpdate,
  ChangeoverMatrix, ChangeoverMatrixCreate, ChangeoverMatrixUpdate,
  BufferConfig, BufferConfigCreate, BufferConfigUpdate,
  SchedulePlan, SchedulePlanCreate, SchedulePlanUpdate,
  ReportWorkOrder, ReportWorkOrderCreate, ReportWorkOrderUpdate,
} from '../types/entities';

export const productApi = createCrudApi<Product, ProductCreate, ProductUpdate>('/products');
export const processInfoApi = createCrudApi<ProcessInfo, ProcessInfoCreate, ProcessInfoUpdate>('/process-info');
export const productionLineApi = createCrudApi<ProductionLine, ProductionLineCreate, ProductionLineUpdate>('/production-lines');
export const productProcessApi = createCrudApi<ProductProcess, ProductProcessCreate, ProductProcessUpdate>('/product-processes');
export const lineProcessConfigApi = createCrudApi<LineProcessConfig, LineProcessConfigCreate, LineProcessConfigUpdate>('/line-process-configs');
export const materialMasterApi = createCrudApi<MaterialMaster, MaterialMasterCreate, MaterialMasterUpdate>('/material-masters');
export const processBOMApi = createCrudApi<ProcessBOM, ProcessBOMCreate, ProcessBOMUpdate>('/process-boms');
export const materialKittingApi = createCrudApi<MaterialKitting, MaterialKittingCreate, MaterialKittingUpdate>('/material-kittings');
export const demandPlanApi = createCrudApi<DemandPlan, DemandPlanCreate, DemandPlanUpdate>('/demand-plans');
export const scheduleResultApi = createCrudApi<ScheduleResult, ScheduleResultCreate, ScheduleResultUpdate>('/schedule-results');
export const resourceCalendarApi = createCrudApi<ResourceCalendar, ResourceCalendarCreate, ResourceCalendarUpdate>('/resource-calendars');
export const changeoverMatrixApi = createCrudApi<ChangeoverMatrix, ChangeoverMatrixCreate, ChangeoverMatrixUpdate>('/changeover-matrices');
export const bufferConfigApi = createCrudApi<BufferConfig, BufferConfigCreate, BufferConfigUpdate>('/buffer-configs');
export const schedulePlanApi = createCrudApi<SchedulePlan, SchedulePlanCreate, SchedulePlanUpdate>('/schedule-plans');
export const reportWorkOrderApi = createCrudApi<ReportWorkOrder, ReportWorkOrderCreate, ReportWorkOrderUpdate>('/report-work-orders');
