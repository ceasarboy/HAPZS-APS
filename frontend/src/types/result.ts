import type { ScheduleStatus } from './schedule';

/** 排产结果 */
export interface ScheduleResult {
  /** 任务ID */
  task_id: string;
  /** 任务状态 */
  status: ScheduleStatus;
  /** 产线计划列表（字段名保留 workcenterPlans 兼容后端） */
  workcenterPlans: WorkCenterPlan[];
  /** 换线信息列表 */
  changeovers: ChangeoverInfo[];
  /** 负荷率信息列表 */
  loadRates: LoadRateInfo[];
  /** OTD率 */
  otdRate: number;
  /** 规则评分报告 */
  ruleReport?: RuleReport;
}

/** 硬规则遵守性项 */
export interface HardRuleItem {
  /** 规则名称 */
  name: string;
  /** 规则编码 */
  code: string;
  /** 遵守状态 PASS/FAIL */
  status: string;
  /** 违反次数 */
  violations: number;
  /** 详情说明 */
  detail: string;
}

/** 软规则评分项 */
export interface SoftScoreItem {
  /** 规则名称 */
  name: string;
  /** 评分 0-1 */
  score: number;
  /** 详情说明 */
  detail: string;
  /** 权重 */
  weight: number;
}

/** 规则评分报告 */
export interface RuleReport {
  /** 硬规则列表 */
  hard_rules: HardRuleItem[];
  /** 硬规则违反总数 */
  hard_violations: number;
  /** 软规则评分 */
  soft_scores: Record<string, SoftScoreItem>;
}

/** 产线计划 */
export interface WorkCenterPlan {
  /** 产线编码 */
  workcenterCode: string;
  /** 产线名称 */
  workcenterName: string;
  /** 计划单元格列表 */
  cells: PlanCell[];
}

/** 计划单元格 */
export interface PlanCell {
  /** 时间段 */
  timeSlot: string;
  /** 产品编码 */
  productCode: string;
  /** 产品名称 */
  productName: string;
  /** 数量 */
  quantity: number;
  /** 是否冻结 */
  frozen: boolean;
  /** 工序编码 */
  processCode?: string;
  /** 工序名称 */
  processName?: string;
  /** 工序顺序 */
  seq?: number;
  /** 约束类型 */
  constraintType?: string;
  /** 优先级：紧急/高/中/低 */
  priority?: string;
  /** 依赖类型：FS/SS/FF/SF */
  dependencyType?: string;
  /** 等待时间（分钟） */
  waitTime?: number;
  /** 准备时间（分钟） */
  prepTime?: number;
}

/** 换线信息 */
export interface ChangeoverInfo {
  /** 产线编码 */
  workcenterCode: string;
  /** 时间段 */
  timeSlot: string;
  /** 当前产品 */
  fromProduct: string;
  /** 下一产品 */
  toProduct: string;
  /** 换线时间（分钟） */
  changeoverTime: number;
}

/** 负荷率信息 */
export interface LoadRateInfo {
  /** 产线名称 */
  workcenterName: string;
  /** 时间段 */
  timeSlot: string;
  /** 负荷率 0-1 */
  loadRate: number;
  /** 计划数量 */
  plannedQty: number;
  /** 产能上限 */
  capacity: number;
}
