import apiClient from './client';
import type {
  ScheduleCreateRequest,
  ScheduleStatusResponse,
  ScheduleListParams,
  ScheduleListItem,
} from '../types/schedule';

/** 创建排产任务 */
export function createSchedule(data: ScheduleCreateRequest) {
  return apiClient.post<ScheduleStatusResponse>('/schedule/create', data);
}

/** 查询排产任务状态 */
export function getScheduleStatus(taskId: string) {
  return apiClient.get<ScheduleStatusResponse>(`/schedule/${taskId}/status`);
}

/** 获取排产任务列表 */
export function getScheduleList(params?: ScheduleListParams) {
  return apiClient.get<ScheduleListItem[]>('/schedule/list', { params });
}

/** 取消排产任务 */
export function cancelSchedule(taskId: string) {
  return apiClient.post(`/schedule/${taskId}/cancel`);
}

/** 紧急插单请求参数 */
export interface InsertOrderParams {
  product_id: string;
  quantity: number;
  due_date: string;
  remark?: string;
}

/** 紧急插单响应 */
export interface InsertOrderResponse {
  row_id: string;
  dp_code: string;
}

/** 紧急插单 */
export function insertUrgentOrder(data: InsertOrderParams) {
  return apiClient.post<InsertOrderResponse>('/schedule/insert-order', data);
}
