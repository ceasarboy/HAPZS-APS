import { useState, useMemo } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu } from 'antd';
import {
  DashboardOutlined,
  ScheduleOutlined,
  SwapOutlined,
  SettingOutlined,
  HistoryOutlined,
  AppstoreOutlined,
  ShopOutlined,
  ToolOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  InboxOutlined,
  CheckSquareOutlined,
  FileTextOutlined,
  CalendarOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  BarChartOutlined,
  TableOutlined,
  ProductOutlined,
  ProfileOutlined,
} from '@ant-design/icons';
import Dashboard from './pages/Dashboard';
import Schedule from './pages/Schedule';
import Changeover from './pages/Changeover';
import Config from './pages/Config';
import History from './pages/History';
import DataManager from './pages/DataManager';
import ScheduleResultPage from './pages/ScheduleResult';
import ReportWork from './pages/ReportWork';
import WorkTimeSettings from './pages/WorkTimeSettings';
import ProcessProgress from './pages/ProcessProgress';

const { Sider, Content, Header } = Layout;

/** 侧边栏菜单项配置 - V3 三级嵌套结构 */
const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/schedule', icon: <ScheduleOutlined />, label: '排产编制' },
  {
    key: 'product-data',
    icon: <ProductOutlined />,
    label: '产品数据',
    children: [
      { key: '/data/products', icon: <AppstoreOutlined />, label: '产品主数据' },
      { key: '/data/product-processes', icon: <ApartmentOutlined />, label: '产品工艺' },
    ],
  },
  {
    key: 'process-data',
    icon: <ToolOutlined />,
    label: '工艺数据',
    children: [
      { key: '/data/production-lines', icon: <ShopOutlined />, label: '产线管理' },
      { key: '/data/process-info', icon: <ToolOutlined />, label: '工序信息' },
      { key: '/data/line-process-configs', icon: <ExperimentOutlined />, label: '产线工艺配置' },
      { key: '/changeover', icon: <SwapOutlined />, label: '换线矩阵' },
      { key: '/data/changeover-matrices', icon: <TableOutlined />, label: '换线矩阵表' },
    ],
  },
  {
    key: 'material-data',
    icon: <InboxOutlined />,
    label: '物料管理',
    children: [
      { key: '/data/material-masters', icon: <InboxOutlined />, label: '物料主数据' },
      { key: '/data/process-boms', icon: <FileTextOutlined />, label: '工序BOM' },
      { key: '/data/material-kittings', icon: <CheckSquareOutlined />, label: '物料齐套' },
    ],
  },
  {
    key: 'production-data',
    icon: <ThunderboltOutlined />,
    label: '生产数据',
    children: [
      { key: '/data/demand-plans', icon: <FileTextOutlined />, label: '需求计划' },
      { key: '/schedule-results', icon: <BarChartOutlined />, label: '派工单' },
      { key: '/data/process-schedule-orders', icon: <ProfileOutlined />, label: '工序计划单' },
      { key: '/process-progress', icon: <BarChartOutlined />, label: '工序进展看板' },
      { key: '/report-work', icon: <CheckSquareOutlined />, label: '报工管理' },
      { key: '/history', icon: <HistoryOutlined />, label: '排产历史' },
      { key: '/data/buffer-configs', icon: <ClockCircleOutlined />, label: '缓冲配置' },
    ],
  },
  {
    key: 'calendar-data',
    icon: <CalendarOutlined />,
    label: '日历管理',
    children: [
      { key: '/data/resource-calendars', icon: <CalendarOutlined />, label: '资源日历' },
      { key: '/work-time-settings', icon: <ClockCircleOutlined />, label: '工作时间设置' },
    ],
  },
  { key: '/config', icon: <SettingOutlined />, label: '系统配置' },
];

/** 应用主布局 - Glassmorphism 风格 */
function App() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // 计算选中的菜单key
  const selectedKeys = [location.pathname];

  // 根据当前路径自动展开对应的父级菜单
  const defaultOpenKeys = useMemo(() => {
    const keys: string[] = [];
    function findPath(items: any[], target: string, parents: string[] = []): string[] | null {
      for (const item of items) {
        if (item.key === target) return [...parents];
        if (item.children) {
          const found = findPath(item.children, target, [...parents, item.key]);
          if (found) return found;
        }
      }
      return null;
    }
    const path = findPath(menuItems, location.pathname);
    if (path) keys.push(...path);
    return keys;
  }, [location.pathname]);

  return (
    <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
      {/* 左侧导航 - Glass Sidebar */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        width={220}
        collapsedWidth={72}
        style={{
          background: 'rgba(255, 255, 255, 0.65)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          borderRight: '1px solid rgba(255, 255, 255, 0.18)',
          overflow: 'auto',
          height: '100vh',
          position: 'sticky',
          top: 0,
          left: 0,
        }}
        trigger={null}
      >
        {/* Logo 区域 - Gradient */}
        <div
          style={{
            height: 52,
            margin: '10px 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 14,
            background: 'linear-gradient(135deg, #1E40AF 0%, #3B82F6 50%, #60A5FA 100%)',
            color: '#fff',
            fontSize: collapsed ? 14 : 15,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            transition: 'all 0.25s cubic-bezier(0.25, 0.1, 0.25, 1)',
            boxShadow: '0 2px 8px rgba(30, 64, 175, 0.25)',
          }}
        >
          {collapsed ? 'APS' : 'APS 排产系统'}
        </div>

        <Menu
          theme="light"
          mode="inline"
          selectedKeys={selectedKeys}
          defaultOpenKeys={defaultOpenKeys}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{
            border: 'none',
            background: 'transparent',
            padding: '0 8px',
          }}
        />

        {/* 折叠按钮 */}
        <div
          onClick={() => setCollapsed(!collapsed)}
          style={{
            position: 'absolute',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 36,
            height: 36,
            borderRadius: 10,
            background: 'rgba(30, 64, 175, 0.06)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1)',
            fontSize: 13,
            color: '#475569',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(30, 64, 175, 0.12)';
            e.currentTarget.style.color = '#1E40AF';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(30, 64, 175, 0.06)';
            e.currentTarget.style.color = '#475569';
          }}
        >
          {collapsed ? '▶' : '◀'}
        </div>
      </Sider>

      <Layout style={{ background: 'transparent' }}>
        {/* 顶部栏 - Glass Header */}
        <Header
          style={{
            padding: '0 28px',
            background: 'rgba(255, 255, 255, 0.55)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(255, 255, 255, 0.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            height: 52,
            lineHeight: '52px',
          }}
        >
          <span style={{
            fontSize: 15,
            fontWeight: 600,
            color: '#1E3A8A',
            letterSpacing: '-0.02em',
          }}>
            高级计划排程系统
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="trust-badge trust-badge-success">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg> 系统在线
            </span>
            <span style={{
              fontSize: 12,
              color: '#94A3B8',
              fontWeight: 500,
              fontFamily: "'Fira Code', monospace",
            }}>
              APS-HAP v3.0
            </span>
          </div>
        </Header>

        {/* 内容区域 */}
        <Content
          style={{
            margin: 20,
            padding: 0,
            background: 'transparent',
            minHeight: 280,
          }}
        >
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/schedule-results" element={<ScheduleResultPage />} />
            <Route path="/report-work" element={<ReportWork />} />
            <Route path="/process-progress" element={<ProcessProgress />} />
            <Route path="/changeover" element={<Changeover />} />
            <Route path="/config" element={<Config />} />
            <Route path="/work-time-settings" element={<WorkTimeSettings />} />
            <Route path="/history" element={<History />} />
            <Route path="/data/:tableKey" element={<DataManager />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}

export default App;
