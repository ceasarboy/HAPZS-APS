import axios from 'axios';
import { message } from 'antd';

/** Axios 实例，统一配置基础URL和拦截器 */
const apiClient = axios.create({
  baseURL: 'http://localhost:8001/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'aps-hap-local-2026',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器：统一错误处理
apiClient.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response) {
      const { status, data } = error.response;
      switch (status) {
        case 401:
          message.error('API Key 验证失败');
          break;
        case 403:
          message.error('没有操作权限');
          break;
        case 404:
          message.error('请求的资源不存在');
          break;
        case 500:
          message.error(data?.message || '服务器内部错误');
          break;
        default:
          message.error(data?.message || `请求失败 (${status})`);
      }
    } else if (error.request) {
      message.error('网络异常，请检查网络连接');
    } else {
      message.error('请求配置错误');
    }
    return Promise.reject(error);
  }
);

export default apiClient;
