import apiClient from './client';
import type { OrderItem, WorkCenterItem, CalendarItem, KittingItem, DemandPlanItem, ProductionLineItem, ProcessInfoItem, ProductProcessItem } from '../types/hap';

/** 获取需求计划列表（V2） */
export function getDemandPlans() {
  return apiClient.get<DemandPlanItem[]>('/hap/demand-plans');
}

/** 产品列表项 */
export interface ProductItem {
  id: string;
  code: string;
  name: string;
}

/** 获取产品列表（供紧急插单选择） */
export function getProducts() {
  return apiClient.get<ProductItem[]>('/hap/products');
}

/** 获取产线列表（V2） */
export function getProductionLines() {
  return apiClient.get<ProductionLineItem[]>('/hap/production-lines');
}

/** 获取工序信息列表（V2） */
export function getProcessInfo() {
  return apiClient.get<ProcessInfoItem[]>('/hap/process-info');
}

/** 获取产品工艺列表（V2） */
export function getProductProcesses() {
  return apiClient.get<ProductProcessItem[]>('/hap/product-processes');
}

/** 获取订单列表参数 */
interface OrderListParams {
  page?: number;
  pageSize?: number;
  status?: string;
}

/** 获取订单列表（V1 兼容） */
export function getOrders(params?: OrderListParams) {
  return apiClient.get<{ total: number; items: OrderItem[] }>('/hap/orders', { params });
}

/** 获取日历信息 */
export function getCalendar() {
  return apiClient.get<CalendarItem[]>('/hap/calendar');
}

/** 获取工作中心列表（V1 兼容） */
export function getWorkcenters() {
  return apiClient.get<WorkCenterItem[]>('/hap/workcenters');
}

/** 获取物料齐套信息 */
export function getKitting() {
  return apiClient.get<KittingItem[]>('/hap/kitting');
}

/** 从 HAP 同步数据 */
export function syncData() {
  return apiClient.post<{ message: string }>('/hap/sync');
}
