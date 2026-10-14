/** V3.9 工作时间模式 API */
import apiClient from './client';

export interface WorkPeriod {
  start: string;
  end: string;
}

export interface BreakPeriod {
  start: string;
  end: string;
  type: string;
}

export interface WorkTimePattern {
  id: string;
  pattern_code?: string;
  pattern_name?: string;
  day_type?: string;
  work_hours?: number;
  slot_duration_minutes?: number;
  work_periods?: WorkPeriod[];
  break_periods?: BreakPeriod[];
  description?: string;
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
}

export const getWorkTimePatterns = async (): Promise<WorkTimePattern[]> => {
  const res = await apiClient.get<WorkTimePattern[]>('/work-time-patterns');
  return res.data;
};

export const getWorkTimePattern = async (id: string): Promise<WorkTimePattern> => {
  const res = await apiClient.get<WorkTimePattern>(`/work-time-patterns/${id}`);
  return res.data;
};

export const createWorkTimePattern = async (data: Partial<WorkTimePattern>): Promise<WorkTimePattern> => {
  const res = await apiClient.post<WorkTimePattern>('/work-time-patterns', data);
  return res.data;
};

export const updateWorkTimePattern = async (id: string, data: Partial<WorkTimePattern>): Promise<WorkTimePattern> => {
  const res = await apiClient.put<WorkTimePattern>(`/work-time-patterns/${id}`, data);
  return res.data;
};

export const deleteWorkTimePattern = async (id: string): Promise<void> => {
  await apiClient.delete(`/work-time-patterns/${id}`);
};
