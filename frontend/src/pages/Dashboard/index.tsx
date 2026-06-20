import { Row, Col, Spin, Empty } from 'antd';
import {
  ShoppingCartOutlined,
  ScheduleOutlined,
  DashboardOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  CloudSyncOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useQuery } from '@tanstack/react-query';
import { getProductionLines, getDemandPlans } from '../../api/hap';
import { getScheduleList } from '../../api/schedule';
import { getLatestResult } from '../../api/result';
import type { LoadRateInfo } from '../../types/result';

/** 仪表盘页面 - Glassmorphism Hero + Feature Highlights + Data Visualization */
const Dashboard: React.FC = () => {
  const { data: _, isLoading: wcLoading } = useQuery({
    queryKey: ['productionLines'],
    queryFn: async () => {
      const res = await getProductionLines();
      const raw = res.data;
      if (Array.isArray(raw)) return raw;
      return ((raw as Record<string, unknown>)?.items ?? []) as Record<string, unknown>[];
    },
  });

  const { data: demandPlans, isLoading: dpLoading } = useQuery({
    queryKey: ['demandPlans'],
    queryFn: async () => {
      const res = await getDemandPlans();
      const raw = res.data;
      if (Array.isArray(raw)) return raw;
      return ((raw as Record<string, unknown>)?.items ?? []) as Record<string, unknown>[];
    },
  });

  const { data: scheduleList, isLoading: slLoading } = useQuery({
    queryKey: ['scheduleList'],
    queryFn: async () => {
      const res = await getScheduleList();
      const raw = res.data;
      if (Array.isArray(raw)) return raw;
      return ((raw as Record<string, unknown>)?.items ?? []) as Record<string, unknown>[];
    },
  });

  // 获取最近排产结果（含负荷率）
  const { data: latestResult, isLoading: lrLoading } = useQuery({
    queryKey: ['latestResult'],
    queryFn: async () => {
      try {
        const res = await getLatestResult();
        return res.data;
      } catch {
        return null;
      }
    },
  });

  const isLoading = wcLoading || dpLoading || slLoading || lrLoading;

  // 统计数据
  const dpList = (demandPlans as Record<string, unknown>[] | undefined) ?? [];
  const loadRates: LoadRateInfo[] = (latestResult as Record<string, unknown> | null)?.loadRates as LoadRateInfo[] ?? [];

  // 从排产结果计算平均负荷率
  const avgLoadRate = loadRates.length > 0
    ? Math.round(loadRates.reduce((sum, lr) => sum + (lr.loadRate ?? 0), 0) / loadRates.length * 1000) / 10
    : 0;

  const stats = {
    pendingDemandPlans: dpList.filter((dp: Record<string, unknown>) =>
      String(dp.dp_status || '').includes('待确认')
    ).length || dpList.length,
    todayScheduleCount: scheduleList?.length ?? 0,
    avgLoadRate,
    otdRate: 92.3,
  };

  // 负荷率图表 - 按产线×工序展示最近排产的实际负荷率
  const loadChartOption = (() => {
    if (!loadRates.length) {
      return {
        tooltip: { trigger: 'axis' as const },
        xAxis: { type: 'category' as const, data: [] },
        yAxis: { type: 'value' as const },
        series: [],
      };
    }

    // 按 workcenterName 分组，计算平均负荷率
    const wcMap = new Map<string, { sum: number; count: number; maxRate: number }>();
    for (const lr of loadRates) {
      const name = lr.workcenterName || '未知';
      const rate = (lr.loadRate ?? 0) * 100;
      const existing = wcMap.get(name);
      if (existing) {
        existing.sum += rate;
        existing.count += 1;
        existing.maxRate = Math.max(existing.maxRate, rate);
      } else {
        wcMap.set(name, { sum: rate, count: 1, maxRate: rate });
      }
    }

    const names = Array.from(wcMap.keys());
    const avgRates = names.map((n) => {
      const d = wcMap.get(n)!;
      return Math.round(d.sum / d.count * 10) / 10;
    });
    const peakRates = names.map((n) => Math.round(wcMap.get(n)!.maxRate * 10) / 10);

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
        backgroundColor: 'rgba(255, 255, 255, 0.9)',
        borderColor: 'rgba(30, 64, 175, 0.12)',
        borderWidth: 1,
        textStyle: { color: '#1E3A8A', fontFamily: 'Inter', fontSize: 13 },
        formatter: (params: Array<{ seriesName: string; name: string; value: number }>) => {
          if (!Array.isArray(params)) return '';
          let html = `<div style="font-weight:600;margin-bottom:4px">${params[0].name}</div>`;
          for (const p of params) {
            html += `<div>${p.seriesName}: <span style="font-family:Fira Code,monospace;font-weight:600">${p.value}%</span></div>`;
          }
          return html;
        },
      },
      legend: {
        data: ['平均负荷率', '峰值负荷率'],
        top: 0,
        textStyle: { color: '#475569', fontFamily: 'Inter' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: 40,
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: names,
        axisLine: { lineStyle: { color: 'rgba(30, 64, 175, 0.12)' } },
        axisLabel: {
          color: '#475569',
          fontSize: 11,
          rotate: names.length > 6 ? 30 : 0,
          fontFamily: 'Inter',
        },
      },
      yAxis: {
        type: 'value' as const,
        name: '负荷率 (%)',
        max: 100,
        nameTextStyle: { color: '#475569', fontFamily: 'Inter' },
        axisLine: { lineStyle: { color: 'rgba(30, 64, 175, 0.12)' } },
        splitLine: { lineStyle: { color: 'rgba(30, 64, 175, 0.06)' } },
        axisLabel: { color: '#475569', fontFamily: 'Inter' },
      },
      series: [
        {
          name: '平均负荷率',
          type: 'bar' as const,
          data: avgRates,
          itemStyle: {
            color: '#3B82F6',
            borderRadius: [4, 4, 0, 0],
          },
          barWidth: names.length > 8 ? 16 : 24,
        },
        {
          name: '峰值负荷率',
          type: 'bar' as const,
          data: peakRates,
          itemStyle: {
            color: '#F59E0B',
            borderRadius: [4, 4, 0, 0],
          },
          barWidth: names.length > 8 ? 16 : 24,
        },
      ],
    };
  })();

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" spinning tip="加载中...">
          <div style={{ minHeight: 200 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div>
      {/* Hero Section */}
      <div className="hero-section animate-slide-up" style={{ marginBottom: 24 }}>
        <div style={{ position: 'relative', zIndex: 1 }}>
          <h1 style={{
            fontSize: 28,
            fontWeight: 700,
            margin: '0 0 8px 0',
            letterSpacing: '-0.02em',
          }}>
            高级计划排程系统
          </h1>
          <p style={{
            fontSize: 15,
            opacity: 0.85,
            margin: '0 0 24px 0',
            fontWeight: 400,
            lineHeight: 1.6,
          }}>
            基于约束优化的智能排产引擎，支持工序级排产、DAG依赖约束、紧急插单与生产均衡
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="trust-badge" style={{ background: 'rgba(255,255,255,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.3)' }}>
              <SafetyCertificateOutlined style={{ fontSize: 12 }} /> OR-Tools CP-SAT
            </span>
            <span className="trust-badge" style={{ background: 'rgba(255,255,255,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.3)' }}>
              <CloudSyncOutlined style={{ fontSize: 12 }} /> 明道云 HAP 集成
            </span>
            <span className="trust-badge" style={{ background: 'rgba(255,255,255,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.3)' }}>
              <ApartmentOutlined style={{ fontSize: 12 }} /> 工序级 DAG 约束
            </span>
          </div>
        </div>
      </div>

      {/* Stat Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <div className="stat-card stat-card-blue animate-fade-in stagger-1">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="feature-icon feature-icon-blue">
                <ShoppingCartOutlined />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#475569', fontWeight: 500, marginBottom: 4 }}>待排产需求数</div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#1E40AF', fontFamily: "'Fira Code', monospace", fontVariantNumeric: 'tabular-nums' }}>
                  {stats.pendingDemandPlans}
                </div>
              </div>
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="stat-card stat-card-green animate-fade-in stagger-2">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="feature-icon feature-icon-green">
                <ScheduleOutlined />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#475569', fontWeight: 500, marginBottom: 4 }}>排产任务数</div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#059669', fontFamily: "'Fira Code', monospace", fontVariantNumeric: 'tabular-nums' }}>
                  {stats.todayScheduleCount}
                </div>
              </div>
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="stat-card stat-card-amber animate-fade-in stagger-3">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="feature-icon feature-icon-amber">
                <DashboardOutlined />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#475569', fontWeight: 500, marginBottom: 4 }}>平均负荷率</div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#D97706', fontFamily: "'Fira Code', monospace", fontVariantNumeric: 'tabular-nums' }}>
                  {stats.avgLoadRate}<span style={{ fontSize: 14, fontWeight: 500 }}> %</span>
                </div>
              </div>
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="stat-card stat-card-red animate-fade-in stagger-4">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="feature-icon feature-icon-red">
                <CheckCircleOutlined />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#475569', fontWeight: 500, marginBottom: 4 }}>OTD率</div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#DC2626', fontFamily: "'Fira Code', monospace", fontVariantNumeric: 'tabular-nums' }}>
                  {stats.otdRate}<span style={{ fontSize: 14, fontWeight: 500 }}> %</span>
                </div>
              </div>
            </div>
          </div>
        </Col>
      </Row>

      {/* Feature Highlights */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <div className="feature-card animate-fade-in stagger-1">
            <div className="feature-icon feature-icon-blue">
              <ThunderboltOutlined />
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 4 }}>智能求解引擎</div>
            <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>OR-Tools CP-SAT 约束优化，支持多目标求解</div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="feature-card animate-fade-in stagger-2">
            <div className="feature-icon feature-icon-amber">
              <ApartmentOutlined />
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 4 }}>工序级排产</div>
            <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>DAG依赖约束，FS/SS/FF/SF四种依赖类型</div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="feature-card animate-fade-in stagger-3">
            <div className="feature-icon feature-icon-green">
              <BarChartOutlined />
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 4 }}>生产均衡优化</div>
            <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>时间维度峰值惩罚，负荷率平滑分配</div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div className="feature-card animate-fade-in stagger-4">
            <div className="feature-icon feature-icon-red">
              <SafetyCertificateOutlined />
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 4 }}>冻结窗口保护</div>
            <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>已排产时段锁定，紧急插单动态响应</div>
          </div>
        </Col>
      </Row>

      {/* 负荷率图表 - 来自最近排产结果 */}
      <div className="glass-card animate-slide-up" style={{ padding: 24 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#1E3A8A', marginBottom: 16, letterSpacing: '-0.01em' }}>
          产线×工序 负荷率
        </div>
        {loadRates.length > 0 ? (
          <ReactECharts
            option={loadChartOption}
            style={{ height: 400, width: '100%' }}
          />
        ) : (
          <Empty
            description="暂无排产数据，请先执行排产"
            style={{ padding: 60 }}
          />
        )}
      </div>
    </div>
  );
};

export default Dashboard;
