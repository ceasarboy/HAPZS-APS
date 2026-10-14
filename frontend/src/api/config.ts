import apiClient from './client';
import type { ScheduleConfig, SolverType } from '../types/schedule';

/** 系统配置 */
export interface SystemConfig {
  solver_type: SolverType;
  start_time: string;
  end_time: string;
  config: ScheduleConfig;
}

/** HAP 鉴权配置 */
export interface HapConfig {
  hap_app_id: string;
  hap_app_key: string;
  hap_sign: string;
  hap_base_url: string;
}

/** 预设配置 */
export interface PresetItem {
  name: string;
  description: string;
  config: SystemConfig;
}

/** 获取系统配置 */
export function getConfig() {
  return apiClient.get<SystemConfig>('/config');
}

/** 更新系统配置 */
export function updateConfig(data: SystemConfig) {
  return apiClient.put<{ message: string }>('/config', data);
}

/** 获取预设配置列表 */
export function getPresets() {
  return apiClient.get<PresetItem[]>('/config/presets');
}

/** 获取 HAP 鉴权配置 */
export function getHapConfig() {
  return apiClient.get<HapConfig>('/config/hap');
}

/** 更新 HAP 鉴权配置 */
export function updateHapConfig(data: HapConfig) {
  return apiClient.put<{ message: string }>('/config/hap', data);
}
