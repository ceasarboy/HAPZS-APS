import apiClient from './client';
import type { ScheduleResult } from '../types/result';

/** 获取排产结果 */
export function getResult(taskId: string) {
  return apiClient.get<ScheduleResult>(`/result/${taskId}`);
}

/** 导出 CSV */
export function exportCsv(taskId: string) {
  return apiClient.get(`/result/${taskId}/export`, { responseType: 'blob' });
}

/** 调整计划 */
export function adjustPlan(taskId: string, data: Record<string, unknown>) {
  return apiClient.post(`/result/${taskId}/adjust`, data);
}

/** 推送结果到 HAP */
export function pushToHap(taskId: string) {
  return apiClient.post<{ message: string }>(`/result/${taskId}/push`);
}

/** 获取最近一次排产结果 */
export function getLatestResult() {
  return apiClient.get<ScheduleResult>('/result/latest');
}
