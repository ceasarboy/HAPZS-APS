/** V3 通用 CRUD 类型定义 */

/** 同步状态枚举 */
export type SyncStatus = 'synced' | 'pending_create' | 'pending_update' | 'pending_delete';

/** 同步基类字段（所有表共有） */
export interface SyncBase {
  id: string;
  hap_row_id: string | null;
  sync_status: SyncStatus | null;
  synced_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 分页参数 */
export interface PaginationParams {
  skip?: number;
  limit?: number;
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

/** CRUD API 工厂返回类型 */
export interface CrudApi<T, C, U> {
  getList: (params?: PaginationParams) => Promise<PaginatedResponse<T>>;
  getById: (id: string) => Promise<T>;
  create: (data: C) => Promise<T>;
  update: (id: string, data: U) => Promise<T>;
  remove: (id: string) => Promise<void>;
}

/** 表单字段配置 */
export interface FieldConfig {
  /** 字段名 */
  name: string;
  /** 显示标签 */
  label: string;
  /** 字段类型 */
  type: 'text' | 'number' | 'select' | 'date' | 'boolean' | 'textarea';
  /** 是否必填（创建时） */
  required?: boolean;
  /** 是否在列表中显示 */
  showInTable?: boolean;
  /** 是否在表单中显示 */
  showInForm?: boolean;
  /** 选择框选项 */
  options?: { label: string; value: string }[];
  /** 占位文本 */
  placeholder?: string;
  /** 列表列宽 */
  width?: number;
  /** 是否为关联字段（显示为链接） */
  isRelation?: boolean;
  /** 关联表名 */
  relationTable?: string;
  /** 关联表显示字段名（如 prod_name, proc_name, line_name） */
  relationLabel?: string;
}

/** 表配置 */
export interface TableConfig<T, C, U> {
  /** 表名（中文） */
  title: string;
  /** API 端点前缀 */
  endpoint: string;
  /** 字段配置 */
  fields: FieldConfig[];
  /** API 实例 */
  api: CrudApi<T, C, U>;
  /** 行选择唯一标识字段 */
  rowKey?: string;
}
