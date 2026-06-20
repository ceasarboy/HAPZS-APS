import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './index.css';

/** React Query 客户端实例 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** Ant Design Glassmorphism 主题配置 */
const glassTheme = {
  token: {
    // Colors - Glassmorphism Blue + Amber Accent
    colorPrimary: '#1E40AF',
    colorSuccess: '#059669',
    colorWarning: '#D97706',
    colorError: '#DC2626',
    colorInfo: '#3B82F6',
    colorBgBase: '#F0F4FF',
    colorBgContainer: 'rgba(255, 255, 255, 0.55)',
    colorBgElevated: 'rgba(255, 255, 255, 0.72)',
    colorBorder: 'rgba(30, 64, 175, 0.12)',
    colorBorderSecondary: 'rgba(30, 64, 175, 0.06)',
    colorText: '#1E3A8A',
    colorTextSecondary: '#475569',
    colorTextTertiary: '#94A3B8',

    // Typography
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontSize: 14,
    fontWeightStrong: 600,
    lineHeight: 1.5,

    // Border Radius
    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,

    // Spacing
    padding: 16,
    paddingLG: 20,
    paddingSM: 12,
    paddingXS: 8,

    // Shadows
    boxShadow: '0 4px 16px rgba(30, 64, 175, 0.06), 0 1px 4px rgba(30, 64, 175, 0.03)',
    boxShadowSecondary: '0 8px 32px rgba(30, 64, 175, 0.10), 0 2px 8px rgba(30, 64, 175, 0.05)',

    // Motion
    motionDurationSlow: '0.25s',
    motionDurationMid: '0.15s',
    motionDurationFast: '0.1s',
    motionEaseInOut: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
  },
  components: {
    Card: {
      borderRadiusLG: 20,
      paddingLG: 20,
    },
    Button: {
      borderRadius: 8,
      fontWeight: 500,
      controlHeight: 36,
      controlHeightLG: 44,
      controlHeightSM: 28,
      primaryShadow: '0 2px 8px rgba(30, 64, 175, 0.25)',
    },
    Table: {
      borderRadius: 16,
      headerBg: 'rgba(30, 64, 175, 0.04)',
      headerColor: '#475569',
      headerFontWeight: 600,
      fontSize: 14,
    },
    Modal: {
      borderRadiusLG: 24,
    },
    Tabs: {
      horizontalMargin: '0 0 0 0',
      inkBarColor: '#1E40AF',
      itemActiveColor: '#1E40AF',
      itemSelectedColor: '#1E40AF',
    },
    Menu: {
      itemBorderRadius: 8,
      itemMarginInline: 8,
      itemMarginBlock: 2,
      activeBarBorderWidth: 0,
    },
    Input: {
      borderRadius: 8,
    },
    Select: {
      borderRadius: 8,
    },
    Tag: {
      borderRadiusSM: 6,
    },
  },
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN} theme={glassTheme}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
