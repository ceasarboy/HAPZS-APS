/** 工序进展看板 - 订单视角，展示每道工序进展 + 最后一道工序交付计划 */

import { useState, useEffect, useMemo } from 'react';
import { Table, Card, Spin, Tag, Progress, Space, Typography, Empty, Select } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import ReactECharts from 'echarts-for-react';
import apiClient from '../../api/client';

const { Title, Text } = Typography;

/** 订单工序进展记录 */
interface OrderProcessRecord {
  demand_id: string;
  dp_code: string;
  product_name: string;
  demand_qty: number;
  seq: number;
  process_name: string;
  planned_qty: number;
  completed_qty: number;
  unfinished_qty: number;
  progress: number;
  expected_complete_date: string | null;
  status: string;
  is_last_process: boolean;
}

/** 交付图表数据 */
interface DeliveryData {
  dates: string[];
  series: { name: string; data: number[] }[];
}

/** 状态颜色映射 */
const statusColorMap: Record<string, string> = {
  '已完成': 'green',
  '报工中': 'processing',
  '已排产': 'blue',
  '待确认': 'gold',
};

/** 订单颜色调色板 */
const ORDER_COLORS = ['#5470C6', '#91CC75', '#FAC858', '#EE6666', '#73C0DE', '#3BA272', '#FC8452', '#9A60B4'];

function ProcessProgress() {
  const [loading, setLoading] = useState(false);
  const [orders, setOrders] = useState<OrderProcessRecord[]>([]);
  const [delivery, setDelivery] = useState<DeliveryData>({ dates: [], series: [] });
  const [selectedDemandIds, setSelectedDemandIds] = useState<string[]>([]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await apiClient.get('/report-work/process-progress');
      setOrders(res.data.orders || []);
      setDelivery(res.data.delivery || { dates: [], series: [] });
    } catch (e: any) {
      setOrders([]);
      setDelivery({ dates: [], series: [] });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  /** 订单选项（去重，按 demand_id） */
  const orderOptions = useMemo(() => {
    const map = new Map<string, { label: string; value: string }>();
    orders.forEach((o) => {
      if (!map.has(o.demand_id)) {
        map.set(o.demand_id, {
          label: `${o.dp_code} (${o.product_name})`,
          value: o.demand_id,
        });
      }
    });
    return Array.from(map.values());
  }, [orders]);

  /** 过滤后的订单数据（按选中订单筛选，按 demand_id 分组，组内按 seq 升序） */
  const filteredOrders = useMemo(() => {
    let list = orders;
    if (selectedDemandIds.length > 0) {
      list = list.filter((o) => selectedDemandIds.includes(o.demand_id));
    }
    // 按 demand_id 分组，组内按 seq 升序排列
    const groups = new Map<string, OrderProcessRecord[]>();
    list.forEach((o) => {
      if (!groups.has(o.demand_id)) groups.set(o.demand_id, []);
      groups.get(o.demand_id)!.push(o);
    });
    // 每组内按 seq 升序排序，然后按组顺序拼接
    const result: OrderProcessRecord[] = [];
    Array.from(groups.values()).forEach((group) => {
      group.sort((a, b) => a.seq - b.seq);
      result.push(...group);
    });
    return result;
  }, [orders, selectedDemandIds]);

  /** 过滤后的交付图表数据 */
  const filteredDelivery = useMemo(() => {
    if (selectedDemandIds.length === 0) return delivery;
    // 按选中订单过滤 series
    const selectedDpCodes = new Set(
      orders
        .filter((o) => selectedDemandIds.includes(o.demand_id))
        .map((o) => o.dp_code)
    );
    return {
      dates: delivery.dates,
      series: delivery.series.filter((s) => selectedDpCodes.has(s.name)),
    };
  }, [delivery, orders, selectedDemandIds]);

  /** 交付图表 option */
  const deliveryOption = useMemo(() => {
    if (!filteredDelivery.dates.length) return null;
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: any[]) => {
          let tip = `${params[0].axisName}<br/>`;
          let total = 0;
          params.forEach((p) => {
            if (p.value > 0) {
              tip += `${p.marker} ${p.seriesName}: ${p.value} 台<br/>`;
              total += p.value;
            }
          });
          tip += `<b>合计: ${total} 台</b>`;
          return tip;
        },
      },
      legend: {
        data: filteredDelivery.series.map((s) => s.name),
        top: 'bottom',
      },
      grid: { left: '3%', right: '4%', bottom: '15%', top: '8%', containLabel: true },
      xAxis: {
        type: 'category',
        data: filteredDelivery.dates,
        name: '交付日期',
      },
      yAxis: {
        type: 'value',
        name: '交付数量(台)',
      },
      series: filteredDelivery.series.map((s, idx) => ({
        name: s.name,
        type: 'bar',
        stack: 'delivery',
        data: s.data,
        itemStyle: { color: ORDER_COLORS[idx % ORDER_COLORS.length] },
        label: {
          show: true,
          position: 'inside',
          formatter: (p: any) => (p.value > 0 ? `${p.value}` : ''),
        },
        emphasis: { focus: 'series' },
      })),
    };
  }, [filteredDelivery]);

  /** 表格列定义 */
  const columns: ColumnsType<OrderProcessRecord> = [
    {
      title: '订单编号',
      dataIndex: 'dp_code',
      width: 180,
      fixed: 'left',
      render: (val, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{val}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{record.product_name}</Text>
        </Space>
      ),
    },
    {
      title: '工序',
      dataIndex: 'seq',
      width: 120,
      render: (seq, record) => (
        <Space>
          <Text type="secondary">{seq}.</Text>
          <Text>{record.process_name}</Text>
          {record.is_last_process && <Tag color="orange">末道</Tag>}
        </Space>
      ),
    },
    {
      title: '计划数量',
      dataIndex: 'planned_qty',
      width: 90,
      align: 'right',
      render: (v) => <Text strong>{v}</Text>,
    },
    {
      title: '已完成',
      dataIndex: 'completed_qty',
      width: 90,
      align: 'right',
      render: (v) => <Text style={{ color: '#52c41a' }}>{v}</Text>,
    },
    {
      title: '未完成',
      dataIndex: 'unfinished_qty',
      width: 90,
      align: 'right',
      render: (v) => (v > 0 ? <Text style={{ color: '#ff4d4f' }}>{v}</Text> : <Text>0</Text>),
    },
    {
      title: '完成进度',
      dataIndex: 'progress',
      width: 160,
      render: (progress, record) => {
        const color = progress >= 100 ? '#52c41a' : progress > 0 ? '#1677ff' : '#d9d9d9';
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Progress percent={Math.min(progress, 100)} size="small" strokeColor={color} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.completed_qty}/{record.planned_qty} ({progress}%)
            </Text>
          </Space>
        );
      },
    },
    {
      title: '预计完成',
      dataIndex: 'expected_complete_date',
      width: 120,
      render: (val) => (val ? <Text>{val}</Text> : <Text type="secondary">-</Text>),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (val) => <Tag color={statusColorMap[val] || 'default'}>{val}</Tag>,
    },
  ];

  return (
    <div style={{ padding: '16px 24px' }}>
      <Spin spinning={loading}>
        {/* 订单筛选 */}
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Text strong>订单筛选：</Text>
            <Select
              mode="multiple"
              allowClear
              placeholder="全部订单（不选则显示全部）"
              style={{ minWidth: 400 }}
              value={selectedDemandIds}
              onChange={setSelectedDemandIds}
              options={orderOptions}
              maxTagPlaceholder={(omitted) => `+${omitted.length}个订单`}
            />
            {selectedDemandIds.length > 0 && (
              <Text type="secondary">已选 {selectedDemandIds.length} 个订单</Text>
            )}
            <ReloadOutlined onClick={fetchData} style={{ cursor: 'pointer', marginLeft: 'auto' }} />
          </Space>
        </Card>

        {/* 交付计划图表（重点） */}
        <Card
          title={
            <Space>
              <Title level={5} style={{ margin: 0 }}>交付计划（末道工序）</Title>
              <Text type="secondary" style={{ fontSize: 13 }}>按日期×订单堆积展示</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        >
          {deliveryOption ? (
            <ReactECharts option={deliveryOption} style={{ height: 340 }} />
          ) : (
            <Empty description="暂无交付数据" />
          )}
        </Card>

        {/* 订单工序进展表 */}
        <Card
          title={
            <Space>
              <Title level={5} style={{ margin: 0 }}>工序进展明细</Title>
              <Text type="secondary" style={{ fontSize: 13 }}>每道工序的计划/已完成/未完成/预计完成</Text>
            </Space>
          }
        >
          <Table<OrderProcessRecord>
            columns={columns}
            dataSource={filteredOrders}
            rowKey={(r) => `${r.demand_id}-${r.seq}-${r.process_name}`}
            pagination={false}
            scroll={{ x: 1000 }}
            size="small"
            bordered
            rowClassName={(r) => (r.is_last_process ? 'last-process-row' : '')}
          />
        </Card>
      </Spin>
      <style>{`
        .last-process-row { background: #fffbe6 !important; }
        .last-process-row:hover > td { background: #fff1b8 !important; }
      `}</style>
    </div>
  );
}

export default ProcessProgress;
