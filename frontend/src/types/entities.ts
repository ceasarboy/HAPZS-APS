/** 14张业务表的 TypeScript 类型定义（V3） */

import type { SyncBase } from './crud';

// ── 1. 产品主数据 ────────────────────────────────────────────────────────

export interface Product extends SyncBase {
  prod_code: string;
  prod_name: string;
  prod_category: string | null;
  prod_spec: string | null;
  changeover_attr: string | null;
  output_rate: number | null;
  batch_size: number | null;
}

export interface ProductCreate {
  prod_code: string;
  prod_name: string;
  prod_category?: string | null;
  prod_spec?: string | null;
  changeover_attr?: string | null;
  output_rate?: number | null;
  batch_size?: number | null;
}

export interface ProductUpdate {
  prod_code?: string | null;
  prod_name?: string | null;
  prod_category?: string | null;
  prod_spec?: string | null;
  changeover_attr?: string | null;
  output_rate?: number | null;
  batch_size?: number | null;
}

// ── 2. 工序信息 ──────────────────────────────────────────────────────────

export interface ProcessInfo extends SyncBase {
  proc_code: string;
  proc_name: string;
  proc_type: string | null;
  constraint_type: string | null;
  is_qc_point: boolean | null;
  status: string | null;
}

export interface ProcessInfoCreate {
  proc_code: string;
  proc_name: string;
  proc_type?: string | null;
  constraint_type?: string | null;
  is_qc_point?: boolean | null;
  status?: string | null;
}

export interface ProcessInfoUpdate {
  proc_code?: string | null;
  proc_name?: string | null;
  proc_type?: string | null;
  constraint_type?: string | null;
  is_qc_point?: boolean | null;
  status?: string | null;
}

// ── 3. 产线 ──────────────────────────────────────────────────────────────

export interface ProductionLine extends SyncBase {
  line_code: string;
  line_name: string;
  line_type: string | null;
  location: string | null;
  status: string | null;
}

export interface ProductionLineCreate {
  line_code: string;
  line_name: string;
  line_type?: string | null;
  location?: string | null;
  status?: string | null;
}

export interface ProductionLineUpdate {
  line_code?: string | null;
  line_name?: string | null;
  line_type?: string | null;
  location?: string | null;
  status?: string | null;
}

// ── 4. 产品工艺 ──────────────────────────────────────────────────────────

export interface ProductProcess extends SyncBase {
  product_id: string;
  process_id: string;
  seq: number | null;
  auto_type: string | null;
  cycle_time: number | null;
  max_units_per_beat: number | null;
  prep_time: number | null;
  wait_time: number | null;
  dependency_type: string | null;
  wait_includes_offhours: boolean | null;
  is_key: boolean | null;
  remark: string | null;
}

export interface ProductProcessCreate {
  product_id: string;
  process_id: string;
  seq?: number | null;
  auto_type?: string | null;
  cycle_time?: number | null;
  max_units_per_beat?: number | null;
  prep_time?: number | null;
  wait_time?: number | null;
  dependency_type?: string | null;
  wait_includes_offhours?: boolean | null;
  is_key?: boolean | null;
  remark?: string | null;
}

export interface ProductProcessUpdate {
  product_id?: string | null;
  process_id?: string | null;
  seq?: number | null;
  auto_type?: string | null;
  cycle_time?: number | null;
  max_units_per_beat?: number | null;
  prep_time?: number | null;
  wait_time?: number | null;
  dependency_type?: string | null;
  wait_includes_offhours?: boolean | null;
  is_key?: boolean | null;
  remark?: string | null;
}

// ── 5. 产线工艺配置 ──────────────────────────────────────────────────────

export interface LineProcessConfig extends SyncBase {
  lpc_code: string | null;
  line_id: string;
  process_id: string;
  auto_type: string | null;
  is_bottleneck: boolean | null;
  equipment_count: number | null;
  worker_count: number | null;
  status: string | null;
}

export interface LineProcessConfigCreate {
  lpc_code?: string | null;
  line_id: string;
  process_id: string;
  auto_type?: string | null;
  is_bottleneck?: boolean | null;
  equipment_count?: number | null;
  worker_count?: number | null;
  status?: string | null;
}

export interface LineProcessConfigUpdate {
  lpc_code?: string | null;
  line_id?: string | null;
  process_id?: string | null;
  auto_type?: string | null;
  is_bottleneck?: boolean | null;
  equipment_count?: number | null;
  worker_count?: number | null;
  status?: string | null;
}

// ── 6. 物料主数据 ────────────────────────────────────────────────────────

export interface MaterialMaster extends SyncBase {
  mat_code: string;
  mat_name: string;
  mat_type: string | null;
  unit: string | null;
  safety_stock: number | null;
  stock_qty: number | null;
  in_transit: number | null;
  status: string | null;
}

export interface MaterialMasterCreate {
  mat_code: string;
  mat_name: string;
  mat_type?: string | null;
  unit?: string | null;
  safety_stock?: number | null;
  stock_qty?: number | null;
  in_transit?: number | null;
  status?: string | null;
}

export interface MaterialMasterUpdate {
  mat_code?: string | null;
  mat_name?: string | null;
  mat_type?: string | null;
  unit?: string | null;
  safety_stock?: number | null;
  stock_qty?: number | null;
  in_transit?: number | null;
  status?: string | null;
}

// ── 7. 工序BOM ───────────────────────────────────────────────────────────

export interface ProcessBOM extends SyncBase {
  product_id: string;
  process_id: string;
  material_id: string;
  unit_qty: number | null;
  reusable: boolean | null;
  remark: string | null;
}

export interface ProcessBOMCreate {
  product_id: string;
  process_id: string;
  material_id: string;
  unit_qty?: number | null;
  reusable?: boolean | null;
  remark?: string | null;
}

export interface ProcessBOMUpdate {
  product_id?: string | null;
  process_id?: string | null;
  material_id?: string | null;
  unit_qty?: number | null;
  reusable?: boolean | null;
  remark?: string | null;
}

// ── 8. 物料齐套 ──────────────────────────────────────────────────────────

export interface MaterialKitting extends SyncBase {
  demand_id: string;
  product_id: string;
  process_id: string;
  material_id: string;
  required_qty: number | null;
  available_qty: number | null;
  shortage_qty: number | null;
  kitting_date: string | null;
  kitting_status: string | null;
}

export interface MaterialKittingCreate {
  demand_id: string;
  product_id: string;
  process_id: string;
  material_id: string;
  required_qty?: number | null;
  available_qty?: number | null;
  shortage_qty?: number | null;
  kitting_date?: string | null;
  kitting_status?: string | null;
}

export interface MaterialKittingUpdate {
  demand_id?: string | null;
  product_id?: string | null;
  process_id?: string | null;
  material_id?: string | null;
  required_qty?: number | null;
  available_qty?: number | null;
  shortage_qty?: number | null;
  kitting_date?: string | null;
  kitting_status?: string | null;
}

// ── 9. 需求计划 ──────────────────────────────────────────────────────────

export interface DemandPlan extends SyncBase {
  dp_code: string;
  product_id: string;
  quantity: number | null;
  unit: string | null;
  due_date: string | null;
  priority: string | null;
  status: string | null;
  scheduled_qty: number | null;
  remark: string | null;
}

export interface DemandPlanCreate {
  dp_code: string;
  product_id: string;
  quantity?: number | null;
  unit?: string | null;
  due_date?: string | null;
  priority?: string | null;
  status?: string | null;
  scheduled_qty?: number | null;
  remark?: string | null;
}

export interface DemandPlanUpdate {
  dp_code?: string | null;
  product_id?: string | null;
  quantity?: number | null;
  unit?: string | null;
  due_date?: string | null;
  priority?: string | null;
  status?: string | null;
  scheduled_qty?: number | null;
  remark?: string | null;
}

// ── 10. 排产结果 ─────────────────────────────────────────────────────────

export interface ScheduleResult extends SyncBase {
  plan_id: string | null;
  product_id: string | null;
  process_id: string | null;
  line_id: string | null;
  demand_id: string | null;
  sr_date: string | null;
  sr_time_slot: string | null;
  sr_quantity: number | null;
  sr_completed_qty: number | null;
  sr_unfinished_qty: number | null;
  sr_status: string | null;
  process_code: string | null;
  constraint_type: string | null;
  seq: number | null;
  dependency_type: string | null;
  wait_time: number | null;
  prep_time: number | null;
}

export interface ScheduleResultCreate {
  plan_id?: string | null;
  product_id?: string | null;
  process_id?: string | null;
  line_id?: string | null;
  demand_id?: string | null;
  sr_date?: string | null;
  sr_time_slot?: string | null;
  sr_quantity?: number | null;
  sr_completed_qty?: number | null;
  sr_unfinished_qty?: number | null;
  sr_status?: string | null;
  process_code?: string | null;
  constraint_type?: string | null;
  seq?: number | null;
  dependency_type?: string | null;
  wait_time?: number | null;
  prep_time?: number | null;
}

export interface ScheduleResultUpdate {
  plan_id?: string | null;
  product_id?: string | null;
  process_id?: string | null;
  line_id?: string | null;
  demand_id?: string | null;
  sr_date?: string | null;
  sr_time_slot?: string | null;
  sr_quantity?: number | null;
  sr_completed_qty?: number | null;
  sr_unfinished_qty?: number | null;
  sr_status?: string | null;
  process_code?: string | null;
  constraint_type?: string | null;
  seq?: number | null;
  dependency_type?: string | null;
  wait_time?: number | null;
  prep_time?: number | null;
}

// ── 11. 资源日历 ─────────────────────────────────────────────────────────

export interface ResourceCalendar extends SyncBase {
  rc_code: string;
  rc_date: string | null;
  rc_hour: number | null;
  line_id: string | null;
  process_id: string | null;
  available_capacity: number | null;
  is_working: boolean | null;
}

export interface ResourceCalendarCreate {
  rc_code: string;
  rc_date?: string | null;
  rc_hour?: number | null;
  line_id?: string | null;
  process_id?: string | null;
  available_capacity?: number | null;
  is_working?: boolean | null;
}

export interface ResourceCalendarUpdate {
  rc_code?: string | null;
  rc_date?: string | null;
  rc_hour?: number | null;
  line_id?: string | null;
  process_id?: string | null;
  available_capacity?: number | null;
  is_working?: boolean | null;
}

// ── 12. 换线矩阵 ────────────────────────────────────────────────────────

export interface ChangeoverMatrix extends SyncBase {
  from_product_id: string | null;
  to_product_id: string | null;
  from_lpc_id: string | null;
  to_lpc_id: string | null;
  changeover_type: string | null;
  setup_time: number | null;
}

export interface ChangeoverMatrixCreate {
  from_product_id?: string | null;
  to_product_id?: string | null;
  from_lpc_id?: string | null;
  to_lpc_id?: string | null;
  changeover_type?: string | null;
  setup_time?: number | null;
}

export interface ChangeoverMatrixUpdate {
  from_product_id?: string | null;
  to_product_id?: string | null;
  from_lpc_id?: string | null;
  to_lpc_id?: string | null;
  changeover_type?: string | null;
  setup_time?: number | null;
}

// ── 13. 缓冲配置 ────────────────────────────────────────────────────────

export interface BufferConfig extends SyncBase {
  process_id: string;
  buffer_time: number | null;
}

export interface BufferConfigCreate {
  process_id: string;
  buffer_time?: number | null;
}

export interface BufferConfigUpdate {
  process_id?: string | null;
  buffer_time?: number | null;
}

// ── 14. 排产方案 ────────────────────────────────────────────────────────

export interface SchedulePlan extends SyncBase {
  sp_name: string;
  sp_status: string | null;
  sp_start_date: string | null;
  sp_end_date: string | null;
  sp_solver: string | null;
  sp_solve_status: string | null;
  sp_solve_time: number | null;
  sp_task_count: number | null;
  sp_total_output: number | null;
}

export interface SchedulePlanCreate {
  sp_name: string;
  sp_status?: string | null;
  sp_start_date?: string | null;
  sp_end_date?: string | null;
  sp_solver?: string | null;
  sp_solve_status?: string | null;
  sp_solve_time?: number | null;
  sp_task_count?: number | null;
  sp_total_output?: number | null;
}

export interface SchedulePlanUpdate {
  sp_name?: string | null;
  sp_status?: string | null;
  sp_start_date?: string | null;
  sp_end_date?: string | null;
  sp_solver?: string | null;
  sp_solve_status?: string | null;
  sp_solve_time?: number | null;
  sp_task_count?: number | null;
  sp_total_output?: number | null;
}

// ── 15. 报工工单 ────────────────────────────────────────────────────────

export interface ReportWorkOrder extends SyncBase {
  dispatch_id: string | null;
  product_id: string | null;
  process_id: string | null;
  line_id: string | null;
  rw_date: string | null;
  rw_time_slot: string | null;
  rw_plan_qty: number | null;
  rw_actual_qty: number | null;
  rw_defect_qty: number | null;
  rw_status: string | null;
  rw_remark: string | null;
}

export interface ReportWorkOrderCreate {
  dispatch_id?: string | null;
  product_id?: string | null;
  process_id?: string | null;
  line_id?: string | null;
  rw_date?: string | null;
  rw_time_slot?: string | null;
  rw_plan_qty?: number | null;
  rw_actual_qty?: number | null;
  rw_defect_qty?: number | null;
  rw_status?: string | null;
  rw_remark?: string | null;
}

export interface ReportWorkOrderUpdate {
  dispatch_id?: string | null;
  product_id?: string | null;
  process_id?: string | null;
  line_id?: string | null;
  rw_date?: string | null;
  rw_time_slot?: string | null;
  rw_plan_qty?: number | null;
  rw_actual_qty?: number | null;
  rw_defect_qty?: number | null;
  rw_status?: string | null;
  rw_remark?: string | null;
}
