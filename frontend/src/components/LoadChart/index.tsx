import ReactECharts from 'echarts-for-react';
import type { LoadRateInfo } from '../../types/result';

/** 负荷率图表组件属性 */
interface LoadChartProps {
  /** 负荷率数据 */
  loadRates: LoadRateInfo[];
  /** 工作中心名称列表（可选，用于筛选） */
  workCenterNames?: string[];
}

/** 负荷率曲线图组件 */
const LoadChart: React.FC<LoadChartProps> = ({ loadRates = [], workCenterNames }) => {
  // 按工作中心分组数据
  const filteredRates = workCenterNames
    ? loadRates.filter((r) => workCenterNames.includes(r.workcenterName))
    : loadRates;

  if (filteredRates.length === 0) {
    return <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无负荷率数据</div>;
  }

  const workcenterSet = Array.from(new Set(filteredRates.map((r) => r.workcenterName)));
  const timeSlots = Array.from(new Set(filteredRates.map((r) => r.timeSlot))).sort();

  // 构建 (workcenterName, timeSlot) → LoadRateInfo 的映射，用于 tooltip
  const dataMap = new Map<string, LoadRateInfo>();
  filteredRates.forEach((r) => {
    dataMap.set(`${r.workcenterName}__${r.timeSlot}`, r);
  });

  // V3.9.2 构建每个产线的曲线系列数据（不再堆叠，每条线独立）
  const series = workcenterSet.map((name) => ({
    name,
    type: 'line' as const,
    smooth: true,
    symbol: 'circle',
    symbolSize: 8,
    data: timeSlots.map((slot) => {
      const item = dataMap.get(`${name}__${slot}`);
      return item ? Math.round(item.loadRate * 100) : 0;
    }),
  }));

  const option = {
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: Array<{ seriesName: string; value: number; axisValue: string }>) => {
        const lines = params
          .filter((p) => p.value > 0)
          .map((p) => {
            const key = `${p.seriesName}__${p.axisValue}`;
            const info = dataMap.get(key);
            const plannedHours = info?.plannedQty ?? 0;
            const capacity = info?.capacity ?? 10.5;
            return `${p.seriesName}: ${p.value}% (排产${plannedHours}h / 产能${capacity}h)`;
          });
        return lines.length > 0
          ? `${params[0]?.axisValue}<br/>${lines.join('<br/>')}`
          : '无数据';
      },
    },
    legend: {
      type: 'scroll' as const,
      data: workcenterSet,
      top: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: 50,
      containLabel: true,
    },
    xAxis: {
      type: 'category' as const,
      name: '日期',
      data: timeSlots,
      axisLabel: {
        rotate: 30,
      },
    },
    yAxis: {
      type: 'value' as const,
      name: '负荷率 (%)',
      max: 100,
      axisLabel: {
        formatter: '{value}%',
      },
    },
    series,
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 450, width: '100%' }}
      notMerge
    />
  );
};

export default LoadChart;
