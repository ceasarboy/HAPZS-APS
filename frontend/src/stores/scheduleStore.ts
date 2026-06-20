import { create } from 'zustand';
import type { ScheduleStatus } from '../types/schedule';
import type { ScheduleResult } from '../types/result';

/** 排产 Store 状态 */
interface ScheduleStoreState {
  /** 当前任务ID */
  currentTaskId: string | null;
  /** 排产状态 */
  scheduleStatus: ScheduleStatus | null;
  /** 排产进度 0-100 */
  progress: number;
  /** 排产结果 */
  result: ScheduleResult | null;

  /** 设置当前任务ID */
  setTaskId: (taskId: string | null) => void;
  /** 设置排产状态 */
  setScheduleStatus: (status: ScheduleStatus | null) => void;
  /** 设置排产进度 */
  setProgress: (progress: number) => void;
  /** 设置排产结果 */
  setResult: (result: ScheduleResult | null) => void;
  /** 重置所有状态 */
  reset: () => void;
}

/** 排产相关全局状态管理 */
export const useScheduleStore = create<ScheduleStoreState>((set) => ({
  currentTaskId: null,
  scheduleStatus: null,
  progress: 0,
  result: null,

  setTaskId: (taskId) => set({ currentTaskId: taskId }),
  setScheduleStatus: (status) => set({ scheduleStatus: status }),
  setProgress: (progress) => set({ progress }),
  setResult: (result) => set({ result }),
  reset: () =>
    set({
      currentTaskId: null,
      scheduleStatus: null,
      progress: 0,
      result: null,
    }),
}));
