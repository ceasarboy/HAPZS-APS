/** 14张业务表的字段配置注册表，驱动通用 CRUD 页面渲染 */

import type { FieldConfig, TableConfig } from '../types/crud';
import {
  productApi, processInfoApi, productionLineApi, productProcessApi,
  lineProcessConfigApi, materialMasterApi, processBOMApi, materialKittingApi,
  demandPlanApi, scheduleResultApi, resourceCalendarApi, changeoverMatrixApi,
  bufferConfigApi, schedulePlanApi, reportWorkOrderApi,
} from '../api/entities';

// ── 通用选项 ──────────────────────────────────────────────────────────────

const autoTypeOptions = [
  { label: '自动', value: '自动' },
  { label: '非自动', value: '非自动' },
];

const constraintTypeOptions = [
  { label: '机时约束', value: '机时约束' },
  { label: '人员工时约束', value: '人员工时约束' },
];

const dependencyTypeOptions = [
  { label: 'FS (完成-开始)', value: 'FS' },
  { label: 'SS (开始-开始)', value: 'SS' },
  { label: 'FF (完成-完成)', value: 'FF' },
  { label: 'SF (开始-完成)', value: 'SF' },
];

const statusOptions = [
  { label: '启用', value: '启用' },
  { label: '停用', value: '停用' },
];

const priorityOptions = [
  { label: '紧急', value: '紧急' },
  { label: '高', value: '高' },
  { label: '中', value: '中' },
  { label: '低', value: '低' },
];

const kittingStatusOptions = [
  { label: '齐套', value: '齐套' },
  { label: '缺料', value: '缺料' },
  { label: '部分齐套', value: '部分齐套' },
];

const demandStatusOptions = [
  { label: '待排产', value: '待排产' },
  { label: '待确认', value: '待确认' },
  { label: '已排产', value: '已排产' },
  { label: '部分排产', value: '部分排产' },
];

const srStatusOptions = [
  { label: '待确认', value: '待确认' },
  { label: '待生产', value: '待生产' },
  { label: '已下发', value: '已下发' },
  { label: '已完成', value: '已完成' },
  { label: '已失效', value: '已失效' },
];

const spStatusOptions = [
  { label: '草稿', value: '草稿' },
  { label: '已求解', value: '已求解' },
  { label: '已下发', value: '已下发' },
];

const solverOptions = [
  { label: 'ortools CP-SAT', value: 'ortools' },
  { label: 'GA 遗传算法', value: 'ga' },
];

const rwStatusOptions = [
  { label: '待报工', value: '待报工' },
  { label: '已报工', value: '已报工' },
  { label: '已关闭', value: '已关闭' },
];

// ── 1. 产品主数据 ────────────────────────────────────────────────────────

const productFields: FieldConfig[] = [
  { name: 'prod_code', label: '产品编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 120 },
  { name: 'prod_name', label: '产品名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 160 },
  { name: 'prod_category', label: '产品分类', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'prod_spec', label: '规格型号', type: 'text', showInTable: true, showInForm: true, width: 120 },
  { name: 'changeover_attr', label: '换型属性', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'output_rate', label: '产出率', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'batch_size', label: '批量大小', type: 'number', showInTable: true, showInForm: true, width: 80 },
];

// ── 2. 工序信息 ──────────────────────────────────────────────────────────

const processInfoFields: FieldConfig[] = [
  { name: 'proc_code', label: '工序编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 100 },
  { name: 'proc_name', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120 },
  { name: 'proc_type', label: '工序类型', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'constraint_type', label: '约束类型', type: 'select', showInTable: true, showInForm: true, width: 120, options: constraintTypeOptions },
  { name: 'is_qc_point', label: '是否质检点', type: 'boolean', showInTable: true, showInForm: true, width: 100 },
  { name: 'status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: statusOptions },
];

// ── 3. 产线 ──────────────────────────────────────────────────────────────

const productionLineFields: FieldConfig[] = [
  { name: 'line_code', label: '产线编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 100 },
  { name: 'line_name', label: '产线名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120 },
  { name: 'line_type', label: '产线类型', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'location', label: '位置', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: statusOptions },
];

// ── 4. 产品工艺 ──────────────────────────────────────────────────────────

const productProcessFields: FieldConfig[] = [
  { name: 'product_id', label: '产品型号', type: 'text', required: true, showInTable: true, showInForm: true, width: 140, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'process_id', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'seq', label: '工序顺序', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'auto_type', label: '工艺类型', type: 'select', showInTable: true, showInForm: true, width: 100, options: autoTypeOptions },
  { name: 'cycle_time', label: '节拍时间(秒)', type: 'number', showInTable: true, showInForm: true, width: 110 },
  { name: 'max_units_per_beat', label: '单节拍最大数量', type: 'number', showInTable: true, showInForm: true, width: 120 },
  { name: 'prep_time', label: '准备时间(分钟)', type: 'number', showInTable: true, showInForm: true, width: 110 },
  { name: 'wait_time', label: '等待时间(分钟)', type: 'number', showInTable: true, showInForm: true, width: 110 },
  { name: 'dependency_type', label: '依赖类型', type: 'select', showInTable: true, showInForm: true, width: 120, options: dependencyTypeOptions },
  { name: 'wait_includes_offhours', label: '下班时间计入等待', type: 'boolean', showInTable: true, showInForm: true, width: 130 },
  { name: 'is_key', label: '关键工序', type: 'boolean', showInTable: true, showInForm: true, width: 80 },
  { name: 'remark', label: '备注', type: 'textarea', showInTable: false, showInForm: true },
];

// ── 5. 产线工艺配置 ──────────────────────────────────────────────────────

const lineProcessConfigFields: FieldConfig[] = [
  { name: 'lpc_code', label: '编号', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'line_id', label: '产线名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'production-lines', relationLabel: 'line_name' },
  { name: 'process_id', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'auto_type', label: '工艺类型', type: 'select', showInTable: true, showInForm: true, width: 100, options: autoTypeOptions },
  { name: 'is_bottleneck', label: '瓶颈工序', type: 'boolean', showInTable: true, showInForm: true, width: 80 },
  { name: 'equipment_count', label: '设备数', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'worker_count', label: '人员数', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: statusOptions },
];

// ── 6. 物料主数据 ────────────────────────────────────────────────────────

const materialMasterFields: FieldConfig[] = [
  { name: 'mat_code', label: '物料编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 120 },
  { name: 'mat_name', label: '物料名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 160 },
  { name: 'mat_type', label: '物料类型', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'unit', label: '单位', type: 'text', showInTable: true, showInForm: true, width: 60 },
  { name: 'safety_stock', label: '安全库存', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'stock_qty', label: '库存数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'in_transit', label: '在途数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: statusOptions },
];

// ── 7. 工序BOM ───────────────────────────────────────────────────────────

const processBOMFields: FieldConfig[] = [
  { name: 'product_id', label: '产品型号', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'process_id', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'material_id', label: '物料名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'material-masters', relationLabel: 'mat_name' },
  { name: 'unit_qty', label: '单位用量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'reusable', label: '可复用', type: 'boolean', showInTable: true, showInForm: true, width: 80 },
  { name: 'remark', label: '备注', type: 'textarea', showInTable: false, showInForm: true },
];

// ── 8. 物料齐套 ──────────────────────────────────────────────────────────

const materialKittingFields: FieldConfig[] = [
  { name: 'demand_id', label: '需求编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 140, isRelation: true, relationTable: 'demand-plans', relationLabel: 'dp_code' },
  { name: 'product_id', label: '产品型号', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'process_id', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'material_id', label: '物料名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'material-masters', relationLabel: 'mat_name' },
  { name: 'required_qty', label: '需求数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'available_qty', label: '可用数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'shortage_qty', label: '缺料数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'kitting_date', label: '齐套日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'kitting_status', label: '齐套状态', type: 'select', showInTable: true, showInForm: true, width: 100, options: kittingStatusOptions },
];

// ── 9. 需求计划 ──────────────────────────────────────────────────────────

const demandPlanFields: FieldConfig[] = [
  { name: 'dp_code', label: '需求编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 140 },
  { name: 'product_id', label: '产品型号', type: 'text', required: true, showInTable: true, showInForm: true, width: 160, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'quantity', label: '需求数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'unit', label: '单位', type: 'text', showInTable: true, showInForm: true, width: 60 },
  { name: 'due_date', label: '交付日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'priority', label: '优先级', type: 'select', showInTable: true, showInForm: true, width: 80, options: priorityOptions },
  { name: 'status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 100, options: demandStatusOptions },
  { name: 'scheduled_qty', label: '已排数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'remark', label: '备注', type: 'textarea', showInTable: false, showInForm: true },
];

// ── 10. 派工单（排产结果） ────────────────────────────────────────────────

const scheduleResultFields: FieldConfig[] = [
  { name: 'plan_id', label: '方案ID', type: 'text', showInTable: false, showInForm: true, width: 200, isRelation: true, relationTable: 'schedule-plans' },
  { name: 'product_id', label: '产品型号', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'process_id', label: '工序名称', type: 'text', showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'line_id', label: '产线名称', type: 'text', showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'production-lines', relationLabel: 'line_name' },
  { name: 'demand_id', label: '需求计划', type: 'text', showInTable: true, showInForm: true, width: 140, isRelation: true, relationTable: 'demand-plans', relationLabel: 'dp_code' },
  { name: 'sr_date', label: '排产日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'sr_time_slot', label: '时段', type: 'text', showInTable: true, showInForm: true, width: 120 },
  { name: 'sr_quantity', label: '排产数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'sr_completed_qty', label: '已完成数量', type: 'number', showInTable: true, showInForm: false, width: 100 },
  { name: 'sr_unfinished_qty', label: '未完成数量', type: 'number', showInTable: true, showInForm: false, width: 100 },
  { name: 'sr_status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: srStatusOptions },
  { name: 'seq', label: '工序顺序', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'dependency_type', label: '依赖类型', type: 'select', showInTable: true, showInForm: true, width: 120, options: dependencyTypeOptions },
  { name: 'wait_time', label: '等待(分)', type: 'number', showInTable: false, showInForm: true, width: 90 },
  { name: 'prep_time', label: '准备(分)', type: 'number', showInTable: false, showInForm: true, width: 90 },
  { name: 'process_code', label: '工序编码', type: 'text', showInTable: false, showInForm: true, width: 100 },
  { name: 'constraint_type', label: '约束类型', type: 'select', showInTable: false, showInForm: true, width: 120, options: constraintTypeOptions },
];

// ── 11. 资源日历 ─────────────────────────────────────────────────────────

const resourceCalendarFields: FieldConfig[] = [
  { name: 'rc_code', label: '资源编码', type: 'text', required: true, showInTable: true, showInForm: true, width: 140 },
  { name: 'rc_date', label: '日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'rc_hour', label: '时段(小时)', type: 'number', showInTable: true, showInForm: true, width: 90 },
  { name: 'line_id', label: '产线名称', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'production-lines', relationLabel: 'line_name' },
  { name: 'process_id', label: '工序名称', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'available_capacity', label: '可用产能', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'is_working', label: '是否工作', type: 'boolean', showInTable: true, showInForm: true, width: 80 },
];

// ── 12. 换线矩阵 ────────────────────────────────────────────────────────

const changeoverMatrixFields: FieldConfig[] = [
  { name: 'changeover_type', label: '换线类型', type: 'select', showInTable: true, showInForm: true, width: 100, options: [
    { label: '产品换线', value: '产品换线' },
    { label: '产线切换', value: '产线切换' },
  ] },
  { name: 'from_product_id', label: '源产品', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'to_product_id', label: '目标产品', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'from_lpc_id', label: '当前产线工艺', type: 'text', showInTable: true, showInForm: true, width: 160, isRelation: true, relationTable: 'line-process-configs', relationLabel: 'lpc_code' },
  { name: 'to_lpc_id', label: '下一产线工艺', type: 'text', showInTable: true, showInForm: true, width: 160, isRelation: true, relationTable: 'line-process-configs', relationLabel: 'lpc_code' },
  { name: 'setup_time', label: '换线时间(分钟)', type: 'number', showInTable: true, showInForm: true, width: 120 },
];

// ── 13. 缓冲配置 ────────────────────────────────────────────────────────

const bufferConfigFields: FieldConfig[] = [
  { name: 'process_id', label: '工序名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'buffer_time', label: '缓冲时间(分钟)', type: 'number', showInTable: true, showInForm: true, width: 120 },
];

// ── 14. 排产方案 ────────────────────────────────────────────────────────

const schedulePlanFields: FieldConfig[] = [
  { name: 'sp_name', label: '方案名称', type: 'text', required: true, showInTable: true, showInForm: true, width: 160 },
  { name: 'sp_status', label: '状态', type: 'select', showInTable: true, showInForm: true, width: 80, options: spStatusOptions },
  { name: 'sp_start_date', label: '开始日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'sp_end_date', label: '结束日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'sp_solver', label: '求解器', type: 'select', showInTable: true, showInForm: true, width: 140, options: solverOptions },
  { name: 'sp_solve_status', label: '求解状态', type: 'text', showInTable: true, showInForm: true, width: 100 },
  { name: 'sp_solve_time', label: '求解耗时(秒)', type: 'number', showInTable: true, showInForm: true, width: 100 },
  { name: 'sp_task_count', label: '任务数', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'sp_total_output', label: '总产出', type: 'number', showInTable: true, showInForm: true, width: 80 },
];

// ── 15. 报工工单 ────────────────────────────────────────────────────────

const reportWorkOrderFields: FieldConfig[] = [
  { name: 'dispatch_id', label: '派工单ID', type: 'text', showInTable: true, showInForm: true, width: 200, isRelation: true, relationTable: 'schedule-results' },
  { name: 'product_id', label: '产品型号', type: 'text', showInTable: true, showInForm: true, width: 120, isRelation: true, relationTable: 'products', relationLabel: 'prod_name' },
  { name: 'process_id', label: '工序名称', type: 'text', showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'process-info', relationLabel: 'proc_name' },
  { name: 'line_id', label: '产线名称', type: 'text', showInTable: true, showInForm: true, width: 100, isRelation: true, relationTable: 'production-lines', relationLabel: 'line_name' },
  { name: 'rw_date', label: '报工日期', type: 'date', showInTable: true, showInForm: true, width: 110 },
  { name: 'rw_time_slot', label: '报工时段', type: 'text', showInTable: true, showInForm: true, width: 140 },
  { name: 'rw_plan_qty', label: '计划数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'rw_actual_qty', label: '实际完成', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'rw_defect_qty', label: '不良数量', type: 'number', showInTable: true, showInForm: true, width: 80 },
  { name: 'rw_status', label: '报工状态', type: 'select', showInTable: true, showInForm: true, width: 100, options: rwStatusOptions },
  { name: 'rw_remark', label: '备注', type: 'textarea', showInTable: false, showInForm: true },
];

// ── 注册表 ────────────────────────────────────────────────────────────────

export type TableKey =
  | 'products'
  | 'process-info'
  | 'production-lines'
  | 'product-processes'
  | 'line-process-configs'
  | 'material-masters'
  | 'process-boms'
  | 'material-kittings'
  | 'demand-plans'
  | 'schedule-results'
  | 'resource-calendars'
  | 'changeover-matrices'
  | 'buffer-configs'
  | 'schedule-plans'
  | 'report-work-orders';

export const tableRegistry: Record<TableKey, TableConfig<any, any, any>> = {
  'products': {
    title: '产品主数据',
    endpoint: '/products',
    fields: productFields,
    api: productApi,
  },
  'process-info': {
    title: '工序信息',
    endpoint: '/process-info',
    fields: processInfoFields,
    api: processInfoApi,
  },
  'production-lines': {
    title: '产线管理',
    endpoint: '/production-lines',
    fields: productionLineFields,
    api: productionLineApi,
  },
  'product-processes': {
    title: '产品工艺',
    endpoint: '/product-processes',
    fields: productProcessFields,
    api: productProcessApi,
  },
  'line-process-configs': {
    title: '产线工艺配置',
    endpoint: '/line-process-configs',
    fields: lineProcessConfigFields,
    api: lineProcessConfigApi,
  },
  'material-masters': {
    title: '物料主数据',
    endpoint: '/material-masters',
    fields: materialMasterFields,
    api: materialMasterApi,
  },
  'process-boms': {
    title: '工序BOM',
    endpoint: '/process-boms',
    fields: processBOMFields,
    api: processBOMApi,
  },
  'material-kittings': {
    title: '物料齐套',
    endpoint: '/material-kittings',
    fields: materialKittingFields,
    api: materialKittingApi,
  },
  'demand-plans': {
    title: '需求计划',
    endpoint: '/demand-plans',
    fields: demandPlanFields,
    api: demandPlanApi,
  },
  'schedule-results': {
    title: '派工单',
    endpoint: '/schedule-results',
    fields: scheduleResultFields,
    api: scheduleResultApi,
  },
  'resource-calendars': {
    title: '资源日历',
    endpoint: '/resource-calendars',
    fields: resourceCalendarFields,
    api: resourceCalendarApi,
  },
  'changeover-matrices': {
    title: '换线矩阵',
    endpoint: '/changeover-matrices',
    fields: changeoverMatrixFields,
    api: changeoverMatrixApi,
  },
  'buffer-configs': {
    title: '缓冲配置',
    endpoint: '/buffer-configs',
    fields: bufferConfigFields,
    api: bufferConfigApi,
  },
  'schedule-plans': {
    title: '排产方案',
    endpoint: '/schedule-plans',
    fields: schedulePlanFields,
    api: schedulePlanApi,
  },
  'report-work-orders': {
    title: '报工工单',
    endpoint: '/report-work-orders',
    fields: reportWorkOrderFields,
    api: reportWorkOrderApi,
  },
};
