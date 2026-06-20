import apiClient from './client';
import type { ChangeoverCell } from '../components/ChangeoverTable';

/** 获取换线矩阵 */
export function getChangeover() {
  return apiClient.get<ChangeoverCell[]>('/changeover');
}

/** 更新换线矩阵 */
export function updateChangeover(data: ChangeoverCell[]) {
  return apiClient.put<{ message: string }>('/changeover', data);
}

/** 从 HAP 同步换线矩阵 */
export function syncChangeover() {
  return apiClient.post<{ message: string }>('/changeover/sync');
}
