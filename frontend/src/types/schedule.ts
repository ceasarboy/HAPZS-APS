/** 排产任务状态 */
export type ScheduleStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'FAILURE';

/** 求解器类型 */
export type SolverType = 'ortools' | 'ga';

/** 硬规则枚举 */
export type HardRule = 'FINITE_CAPACITY' | 'PROCESS_ORDER' | 'RESOURCE_COMPATIBILITY';

/** 软规则枚举 */
export type SoftRule = 'OTD_PRIORITY' | 'SETUP_MINIMIZATION' | 'LOAD_BALANCING';

/** 排产配置 */
export interface ScheduleConfig {
  /** 硬规则列表 */
  hard_rules: HardRule[];
  /** 软规则列表 */
  soft_rules: SoftRule[];
  /** 软规则权重 */
  soft_rule_weights: Record<SoftRule, number>;
}

/** 排产创建请求 */
export interface ScheduleCreateRequest {
  /** 求解器类型 */
  solver_type: SolverType;
  /** 排产开始时间 */
  start_time: string;
  /** 排产结束时间 */
  end_time: string;
  /** 冻结窗口（天），前 N 天的时间槽被锁定，不允许新任务分配 */
  freeze_horizon?: number;
  /** 排产配置（可选） */
  config?: ScheduleConfig;
}

/** 排产结果摘要 */
export interface ResultSummary {
  /** 计划ID */
  plan_id: string;
  /** 求解状态 */
  solve_status: 'OPTIMAL' | 'FEASIBLE' | 'INFEASIBLE';
  /** 任务数量 */
  task_count: number;
  /** 求解耗时（秒） */
  solve_time_seconds: number;
  /** 求解器名称 */
  solver_name: string;
  /** 错误信息 */
  error?: string;
}

/** 排产状态响应 */
export interface ScheduleStatusResponse {
  /** 任务ID */
  task_id: string;
  /** 任务状态 */
  status: ScheduleStatus;
  /** 进度百分比 0-100 */
  progress: number;
  /** 结果摘要（完成时返回） */
  result_summary?: ResultSummary;
}

/** 排产列表查询参数 */
export interface ScheduleListParams {
  /** 页码 */
  page?: number;
  /** 每页数量 */
  pageSize?: number;
  /** 状态筛选 */
  status?: ScheduleStatus;
}

/** 排产列表项 */
export interface ScheduleListItem {
  task_id: string;
  status: ScheduleStatus;
  progress: number;
  result_summary?: ResultSummary;
  created_at?: string;
  finished_at?: string;
}
