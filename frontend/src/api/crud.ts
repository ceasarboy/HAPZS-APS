/** 通用 CRUD API 工厂，为14张业务表自动生成增删改查方法 */

import apiClient from './client';
import type { PaginationParams, PaginatedResponse, CrudApi } from '../types/crud';

/**
 * 创建 CRUD API 实例
 * @param endpoint API 端点前缀，如 '/products'
 */
export function createCrudApi<T, C, U>(endpoint: string): CrudApi<T, C, U> {
  return {
    /** 分页查询列表 */
    async getList(params?: PaginationParams): Promise<PaginatedResponse<T>> {
      const res = await apiClient.get<PaginatedResponse<T>>(endpoint, { params });
      return res.data;
    },

    /** 根据 ID 查询单条 */
    async getById(id: string): Promise<T> {
      const res = await apiClient.get<T>(`${endpoint}/${id}`);
      return res.data;
    },

    /** 创建记录 */
    async create(data: C): Promise<T> {
      const res = await apiClient.post<T>(endpoint, data);
      return res.data;
    },

    /** 更新记录 */
    async update(id: string, data: U): Promise<T> {
      const res = await apiClient.put<T>(`${endpoint}/${id}`, data);
      return res.data;
    },

    /** 删除记录 */
    async remove(id: string): Promise<void> {
      await apiClient.delete(`${endpoint}/${id}`);
    },
  };
}
