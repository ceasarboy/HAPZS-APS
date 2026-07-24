/** 需求计划条目（V2） */
export interface DemandPlanItem {
  /** 需求计划ID */
  id: string;
  /** 需求计划编码 */
  dp_code: string;
  /** 产品ID */
  dp_product: string;
  /** 需求数量 */
  dp_quantity: number;
  /** 单位 */
  dp_unit: string;
  /** 交付日期 */
  dp_due_date: string;
  /** 优先级 */
  dp_priority: string;
  /** 状态 */
  dp_status: string;
  /** 备注 */
  dp_remark: string;
}

/** 产线条目（V2） */
export interface ProductionLineItem {
  /** 产线ID */
  id: string;
  /** 产线编码 */
  line_code: string;
  /** 产线名称 */
  line_name: string;
  /** 产线类型 */
  line_type: string;
  /** 日产能 */
  daily_capacity: number;
  /** 当前负荷 */
  line_load: number;
  /** 效率 */
  efficiency: number;
  /** 状态 */
  status: string;
}

/** 工序信息条目（V2） */
export interface ProcessInfoItem {
  /** 工序ID */
  id: string;
  /** 工序编码 */
  proc_code: string;
  /** 工序名称 */
  proc_name: string;
  /** 约束类型 */
  constraint_type: string;
  /** 工序类型 */
  proc_type: string;
  /** 是否质检点 */
  is_qc_point: string;
  /** 状态 */
  status: string;
}

/** 产品工艺条目（V3） */
export interface ProductProcessItem {
  /** 记录ID */
  id: string;
  /** 产品ID */
  product_id: string;
  /** 工序ID */
  process_id: string;
  /** 工序顺序 */
  seq: number;
  /** 工艺类型：自动/非自动 */
  auto_type: string;
  /** 节拍时间(秒) */
  cycle_time: number;
  /** 单节拍最大数量 */
  max_units_per_beat: number;
  /** 准备时间(分钟) */
  prep_time: number;
  /** 等待时间(分钟) */
  wait_time: number;
  /** 等待时间是否计入下班时间 */
  wait_includes_offhours: string;
  /** 依赖类型：FS/SS/FF/SF */
  dependency_type: string;
  /** 是否关键工序 */
  is_key: string;
  /** 备注 */
  remark: string;
}

/** 订单条目（V1 兼容） */
export interface OrderItem {
  /** 订单ID */
  orderId: string;
  /** 产品编码 */
  productCode: string;
  /** 产品名称 */
  productName: string;
  /** 订单数量 */
  quantity: number;
  /** 交付日期 */
  dueDate: string;
  /** 优先级 */
  priority: number;
  /** 订单状态 */
  status: string;
}

/** 工作中心条目（V1 兼容） */
export interface WorkCenterItem {
  /** 工作中心编码 */
  workcenterCode: string;
  /** 工作中心名称 */
  workcenterName: string;
  /** 日产能 */
  dailyCapacity: number;
  /** 当前负荷 */
  currentLoad: number;
  /** 工作中心类型 */
  type: string;
}

/** 日历条目 */
export interface CalendarItem {
  /** 日期 */
  date: string;
  /** 是否工作日 */
  isWorkday: boolean;
  /** 班次信息 */
  shifts: string[];
  /** 备注 */
  remark?: string;
}

/** 齐套信息条目 */
export interface KittingItem {
  /** 订单ID */
  orderId: string;
  /** 物料编码 */
  materialCode: string;
  /** 物料名称 */
  materialName: string;
  /** 需求数量 */
  requiredQty: number;
  /** 可用数量 */
  availableQty: number;
  /** 是否齐套 */
  isReady: boolean;
}
