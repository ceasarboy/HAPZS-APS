import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { useQuery } from '@tanstack/react-query';
import { Select, Space } from 'antd';
import { getProcessInfo, getProductProcesses, getProducts } from '../../api/hap';
import type { ProcessInfoItem, ProductProcessItem } from '../../types/hap';

interface ProcessFlowProps {
  height?: number;
}

/** 依赖类型连线样式 */
const DEP_LINE_STYLE: Record<string, { type: string; color: string }> = {
  FS: { type: 'solid', color: '#595959' },
  SS: { type: 'dashed', color: '#1890ff' },
  FF: { type: 'dotted', color: '#52c41a' },
  SF: { type: 'dashed', color: '#fa8c16' },
};

export default function ProcessFlow({ height = 625 }: ProcessFlowProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const [selectedProductId, setSelectedProductId] = useState<string | undefined>(undefined);

  const { data: processList = [] } = useQuery({
    queryKey: ['processInfo'],
    queryFn: async () => {
      const res = await getProcessInfo();
      return (res.data as ProcessInfoItem[]) || [];
    },
  });

  const { data: productProcessList = [] } = useQuery({
    queryKey: ['productProcesses'],
    queryFn: async () => {
      const res = await getProductProcesses();
      return (res.data as ProductProcessItem[]) || [];
    },
  });

  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: async () => {
      const res = await getProducts();
      return (res.data as { id: string; code: string; name: string }[]) || [];
    },
  });

  // 默认选中第一个产品
  useEffect(() => {
    if (!selectedProductId && products.length > 0) {
      setSelectedProductId(products[0].id);
    }
  }, [products, selectedProductId]);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }
    const chart = chartInstance.current;

    // 工序 ID → 工序信息映射
    const processMap = new Map<string, ProcessInfoItem>();
    for (const p of processList) {
      processMap.set(p.id, p);
    }

    // 过滤掉 product_id/process_id 为空的脏数据
    const validPP = productProcessList.filter((pp) => pp.product_id && pp.process_id);

    // 筛选产品的工艺路线
    const filteredPP = selectedProductId
      ? validPP.filter((pp) => pp.product_id === selectedProductId)
      : validPP;

    if (filteredPP.length === 0) {
      chart.setOption({
        title: { text: '暂无工艺路线数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
      });
      return;
    }

    // 按 seq 分组，构建节点
    // 当选择"全部产品"时，同一工序可能被多个产品使用，需要去重
    // 当选择单个产品时，每个工序只出现一次
    const seqGroups: Record<number, ProductProcessItem[]> = {};
    const seenProcesses = new Set<string>(); // 去重：同一工序只显示一次

    for (const pp of filteredPP) {
      if (seenProcesses.has(pp.process_id)) continue;
      seenProcesses.add(pp.process_id);
      if (!seqGroups[pp.seq]) seqGroups[pp.seq] = [];
      seqGroups[pp.seq].push(pp);
    }

    const nodes: any[] = [];
    const xSpacing = 160;
    const ySpacing = 110;
    const startX = 80;

    const sortedSeqs = Object.keys(seqGroups).map(Number).sort((a, b) => a - b);

    // 计算最大并行数（同一 seq 中最多的工序数）
    const maxParallel = Math.max(...sortedSeqs.map(s => seqGroups[s].length));

    sortedSeqs.forEach((seq, seqIdx) => {
      const group = seqGroups[seq];
      const yOffset = -(group.length - 1) * ySpacing / 2;
      const centerY = 300; // 容器高度625的中间偏上
      group.forEach((pp, i) => {
        const proc = processMap.get(pp.process_id);
        if (!proc) return;
        const isMachine = proc.constraint_type === '机时约束';
        const isAuto = pp.auto_type === '自动';
        // V3: 工艺参数从 ProductProcess 获取（已从 ProcessInfo 迁移）
        const paramParts = [`节拍${pp.cycle_time}s`];
        if (pp.max_units_per_beat > 1) paramParts.push(`单节拍${pp.max_units_per_beat}`);
        if (pp.prep_time > 0) paramParts.push(`准备${pp.prep_time}min`);
        if (pp.wait_time > 0) paramParts.push(`等待${pp.wait_time}min`);
        const paramLine = paramParts.join(' · ');

        // 节点标签：工序名 + 约束类型 + 工艺类型 + 参数行
        const typeLine = `${proc.constraint_type} · ${isAuto ? '自动' : '非自动'}`;

        nodes.push({
          name: pp.process_id,
          value: {
            ...proc,
            ...pp,
          },
          x: startX + seqIdx * xSpacing,
          y: centerY + yOffset + i * ySpacing,
          symbolSize: [130, 72],
          itemStyle: {
            color: isMachine ? '#e6f7ff' : '#fff7e6',
            borderColor: isMachine ? '#1890ff' : '#fa8c16',
            borderWidth: 2,
            shadowBlur: 4,
            shadowColor: 'rgba(0,0,0,0.08)',
          },
          label: {
            show: true,
            formatter: `{name|${proc.proc_name}}\n{type|${typeLine}}\n{param|${paramLine}}`,
            rich: {
              name: { fontSize: 13, fontWeight: 600, color: '#1a1a1a', lineHeight: 20, align: 'center' as const },
              type: { fontSize: 10, color: '#999', lineHeight: 16, align: 'center' as const },
              param: { fontSize: 10, color: '#595959', lineHeight: 16, align: 'center' as const, backgroundColor: 'rgba(0,0,0,0.04)', padding: [1, 4], borderRadius: 2 },
            },
          },
        });
      });
    });

    // 构建边：相邻 seq 之间的依赖
    const edges: any[] = [];
    for (let si = 1; si < sortedSeqs.length; si++) {
      const prevSeq = sortedSeqs[si - 1];
      const currSeq = sortedSeqs[si];
      const prevGroup = seqGroups[prevSeq];
      const currGroup = seqGroups[currSeq];

      for (const currPP of currGroup) {
        const depType = currPP.dependency_type || 'FS';
        const style = DEP_LINE_STYLE[depType] || DEP_LINE_STYLE['FS'];

        // V3: 延迟从 ProductProcess 获取（wait_time + prep_time）
        let delayText = '';
        if (depType === 'FS') {
          const totalDelay = (currPP.wait_time || 0) + (currPP.prep_time || 0);
          if (totalDelay > 0) delayText = `${totalDelay}min`;
        }

        // 每个前驱 seq 的工序都连到当前工序
        for (const prevPP of prevGroup) {
          edges.push({
            source: prevPP.process_id,
            target: currPP.process_id,
            lineStyle: {
              type: style.type as any,
              color: style.color,
              width: 2,
            },
            label: {
              show: true,
              formatter: delayText ? `${depType} ${delayText}` : depType,
              fontSize: 10,
              color: style.color,
              fontWeight: 600,
              backgroundColor: '#fff',
              padding: [2, 4],
              borderRadius: 3,
            },
          });
        }
      }
    }

    // 产品名称
    const productName = selectedProductId
      ? products.find((p) => p.id === selectedProductId)?.name || '未知产品'
      : '全部产品';

    // 计算自动缩放：让所有节点默认可见
    let autoZoom = 1;
    if (nodes.length > 0 && chartRef.current) {
      const flowW = (sortedSeqs.length - 1) * xSpacing + 130; // 节点宽度
      const flowH = (maxParallel - 1) * ySpacing + 72; // 节点高度
      const containerW = chartRef.current.clientWidth;
      const containerH = height;
      const zoomX = containerW / (flowW + 100);
      const zoomY = containerH / (flowH + 100);
      autoZoom = Math.min(zoomX, zoomY, 1.0);
    }

    chart.setOption({
      tooltip: {
        formatter: (params: any) => {
          if (params.dataType === 'node') {
            const p = params.data.value;
            let info = `<b>${p.proc_name}</b> (${p.proc_code})<br/>`;
            info += `约束类型: ${p.constraint_type}<br/>`;
            info += `工艺类型: ${p.auto_type || '非自动'}<br/>`;
            info += `节拍时间: ${p.cycle_time}s<br/>`;
            if (p.max_units_per_beat > 1) info += `单节拍最大数量: ${p.max_units_per_beat}<br/>`;
            if (p.prep_time > 0) info += `准备时间: ${p.prep_time}min<br/>`;
            if (p.wait_time > 0) {
              const offhours = p.wait_includes_offhours === 'True' || p.wait_includes_offhours === 'true';
              info += `等待时间: ${p.wait_time}min${offhours ? ' (含下班时间)' : ''}<br/>`;
            }
            info += `依赖类型: ${p.dependency_type || 'FS'}<br/>`;
            return info;
          }
          return '';
        },
      },
      title: {
        text: `${productName} 工艺流程图`,
        left: 'center',
        top: 8,
        textStyle: { fontSize: 14, color: '#333' },
      },
      series: [{
        type: 'graph',
        layout: 'none',
        roam: true,
        draggable: true,
        zoom: autoZoom,
        data: nodes,
        links: edges,
        symbol: 'roundRect',
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 10],
        emphasis: {
          focus: 'adjacency',
          itemStyle: { borderWidth: 3 },
        },
      }],
    }, true);
  }, [processList, productProcessList, products, selectedProductId]);

  // resize
  useEffect(() => {
    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <span style={{ fontSize: 13, color: '#666' }}>选择产品：</span>
        <Select
          value={selectedProductId}
          onChange={setSelectedProductId}
          placeholder="全部产品"
          allowClear
          style={{ width: 200 }}
          options={products.map((p) => ({ label: p.name, value: p.id }))}
        />
      </Space>
      <div ref={chartRef} style={{ width: '100%', height }} />
    </div>
  );
}
