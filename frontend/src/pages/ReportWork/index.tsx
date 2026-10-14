/** 报工管理页面 - 含报工弹窗和日终处理 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  Table, Button, Space, Modal, Form, Input, InputNumber,
  Segmented,
  message, Popconfirm, Tag, Tooltip,
} from 'antd';
import {
  ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import apiClient from '../../api/client';

/** 关联表名称字段映射 */
const RELATION_LABEL_MAP: Record<string, string> = {
  'products': 'prod_name',
  'process-info': 'proc_name',
  'production-lines': 'line_name',
  'schedule-results': 'plan_id',
};

/** 关联表API端点映射 */
const RELATION_ENDPOINT_MAP: Record<string, string> = {
  'products': '/products',
  'process-info': '/process-info',
  'production-lines': '/production-lines',
  'schedule-results': '/schedule-results',
};

/** 报工状态 Tag 颜色映射 */
const rwStatusColorMap: Record<string, string> = {
  '待报工': 'blue',
  '已报工': 'green',
  '已关闭': 'default',
};

interface ReportWorkRecord {
  id: string;
  dispatch_id: string | null;
  product_id: string | null;
  process_id: string | null;
  line_id: string | null;
  rw_date: string | null;
  rw_time_slot: string | null;
  rw_plan_qty: number | null;
  rw_actual_qty: number | null;
  rw_defect_qty: number | null;
  rw_status: string | null;
  rw_remark: string | null;
}

export default function ReportWork() {
  const [data, setData] = useState<ReportWorkRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [reportingRecord, setReportingRecord] = useState<ReportWorkRecord | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [dailyResetLoading, setDailyResetLoading] = useState(false);
  const [sortMode, setSortMode] = useState<'time' | 'order'>('time');
  const [form] = Form.useForm();

  // 关联表数据缓存
  const [relationCache, setRelationCache] = useState<Record<string, Record<string, string>>>({});
  const loadedTablesRef = useRef<Set<string>>(new Set());

  /** 加载关联表数据 */
  const loadRelationData = useCallback(async () => {
    const tablesToLoad = ['products', 'process-info', 'production-lines'];
    const newCache: Record<string, Record<string, string>> = {};
    for (const tableKey of tablesToLoad) {
      if (loadedTablesRef.current.has(tableKey)) {
        continue;
      }
      const endpoint = RELATION_ENDPOINT_MAP[tableKey];
      if (!endpoint) continue;
      try {
        const res = await apiClient.get(`${endpoint}?skip=0&limit=1000`);
        const items = res.data?.items || res.data || [];
        const labelField = RELATION_LABEL_MAP[tableKey] || 'name';
        const map: Record<string, string> = {};
        for (const item of items) {
          map[item.id] = item[labelField] || item.id;
        }
        newCache[tableKey] = map;
        loadedTablesRef.current.add(tableKey);
      } catch {
        newCache[tableKey] = {};
      }
    }
    if (Object.keys(newCache).length > 0) {
      setRelationCache(prev => ({ ...prev, ...newCache }));
    }
  }, []);

  /** 获取关联名称 */
  const getRelationLabel = useCallback((tableKey: string, id: string | null): string => {
    if (!id) return '-';
    const cache = relationCache[tableKey];
    if (cache && cache[id]) return cache[id];
    return id.substring(0, 8) + '...';
  }, [relationCache]);

  /** 加载数据 */
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const skip = (page - 1) * pageSize;
      const res = await apiClient.get(`/report-work-orders?skip=${skip}&limit=${pageSize}`);
      setData(res.data?.items || []);
      setTotal(res.data?.total || 0);
    } catch {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  /** 排序后的数据 */
  const sortedData = useMemo(() => {
    const sorted = [...data];
    if (sortMode === 'order') {
      sorted.sort((a, b) => {
        const ka = (a.product_id || '') + '|' + (a.rw_date || '') + (a.rw_time_slot || '');
        const kb = (b.product_id || '') + '|' + (b.rw_date || '') + (b.rw_time_slot || '');
        return ka.localeCompare(kb);
      });
    } else {
      sorted.sort((a, b) => {
        const ka = (a.rw_date || '') + (a.rw_time_slot || '');
        const kb = (b.rw_date || '') + (b.rw_time_slot || '');
        return ka.localeCompare(kb);
      });
    }
    return sorted;
  }, [data, sortMode]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    loadRelationData();
  }, [loadRelationData]);

  /** 打开报工弹窗 */
  const handleOpenReport = (record: ReportWorkRecord) => {
    setReportingRecord(record);
    form.resetFields();
    form.setFieldsValue({
      rw_actual_qty: record.rw_plan_qty,
      rw_defect_qty: 0,
    });
    setReportModalOpen(true);
  };

  /** 提交报工 */
  const handleReportSubmit = async () => {
    if (!reportingRecord?.dispatch_id) {
      message.error('缺少派工单ID');
      return;
    }
    try {
      const values = await form.validateFields();
      setReportLoading(true);
      await apiClient.post(`/report-work/${reportingRecord.dispatch_id}`, {
        rw_actual_qty: values.rw_actual_qty,
        rw_defect_qty: values.rw_defect_qty,
        rw_remark: values.rw_remark || '',
      });
      message.success('报工成功');
      setReportModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (err: any) {
      if (err.errorFields) return;
      message.error('报工失败');
    } finally {
      setReportLoading(false);
    }
  };

  /** 日终处理 */
  const handleDailyReset = async () => {
    setDailyResetLoading(true);
    try {
      await apiClient.post('/report-work/daily-reset');
      message.success('日终处理完成');
      fetchData();
    } catch {
      message.error('日终处理失败');
    } finally {
      setDailyResetLoading(false);
    }
  };

  /** 构建表格列 */
  const columns: ColumnsType<ReportWorkRecord> = [
    {
      title: '序号',
      width: 50,
      render: (_, __, idx) => (page - 1) * pageSize + idx + 1,
      fixed: 'left',
    },
    {
      title: '派工单ID',
      dataIndex: 'dispatch_id',
      key: 'dispatch_id',
      width: 200,
      ellipsis: true,
      render: (val: string | null) => {
        if (!val) return '-';
        return (
          <Tooltip title={val}>
            <Tag color="blue">{val.substring(0, 8)}...</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '派工日期',
      dataIndex: 'rw_date',
      key: 'rw_date',
      width: 100,
      render: (val: string | null) => val || '-',
    },
    {
      title: '时间段',
      dataIndex: 'rw_time_slot',
      key: 'rw_time_slot',
      width: 120,
      render: (val: string | null) => val || '-',
    },
    {
      title: '产品名称',
      dataIndex: 'product_id',
      key: 'product_id',
      width: 120,
      render: (val: string | null) => {
        const label = getRelationLabel('products', val);
        return <Tag color="blue">{label}</Tag>;
      },
    },
    {
      title: '工序名称',
      dataIndex: 'process_id',
      key: 'process_id',
      width: 100,
      render: (val: string | null) => {
        const label = getRelationLabel('process-info', val);
        return <Tag color="blue">{label}</Tag>;
      },
    },
    {
      title: '产线名称',
      dataIndex: 'line_id',
      key: 'line_id',
      width: 100,
      render: (val: string | null) => {
        const label = getRelationLabel('production-lines', val);
        return <Tag color="blue">{label}</Tag>;
      },
    },
    {
      title: '计划数量',
      dataIndex: 'rw_plan_qty',
      key: 'rw_plan_qty',
      width: 80,
      render: (val: number | null) => val ?? '-',
    },
    {
      title: '实际完成',
      dataIndex: 'rw_actual_qty',
      key: 'rw_actual_qty',
      width: 80,
      render: (val: number | null) => val ?? '-',
    },
    {
      title: '不良数量',
      dataIndex: 'rw_defect_qty',
      key: 'rw_defect_qty',
      width: 80,
      render: (val: number | null) => val ?? '-',
    },
    {
      title: '状态',
      dataIndex: 'rw_status',
      key: 'rw_status',
      width: 80,
      render: (val: string | null) => {
        if (!val) return '-';
        return <Tag color={rwStatusColorMap[val] || 'default'}>{val}</Tag>;
      },
    },
    {
      title: '备注',
      dataIndex: 'rw_remark',
      key: 'rw_remark',
      width: 120,
      ellipsis: true,
      render: (val: string | null) => val || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_, record) => {
        if (record.rw_status !== '待报工') return '-';
        return (
          <Button type="link" size="small" onClick={() => handleOpenReport(record)}>
            报工
          </Button>
        );
      },
    },
  ];

  return (
    <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: 12, padding: 20, backdropFilter: 'blur(8px)' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1E3A8A' }}>报工管理</h2>
        <Space>
          <Popconfirm
            title="日终处理"
            description="确认执行日终处理？将关闭所有已报工的工单。"
            onConfirm={handleDailyReset}
            okText="确认"
            cancelText="取消"
          >
            <Button icon={<ThunderboltOutlined />} loading={dailyResetLoading}>
              日终处理
            </Button>
          </Popconfirm>
          <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          <Segmented
            value={sortMode}
            onChange={(v) => setSortMode(v as 'time' | 'order')}
            options={[
              { label: '按时间', value: 'time' },
              { label: '按订单', value: 'order' },
            ]}
          />
        </Space>
      </div>

      {/* 数据表格 */}
      <Table
        columns={columns}
        dataSource={sortedData}
        rowKey="id"
        loading={loading}
        scroll={{ x: 'max-content' }}
        size="small"
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />

      {/* 报工弹窗 */}
      <Modal
        title="报工"
        open={reportModalOpen}
        onOk={handleReportSubmit}
        onCancel={() => { setReportModalOpen(false); form.resetFields(); }}
        confirmLoading={reportLoading}
        okText="提交"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="rw_actual_qty"
            label="实际完成数量"
            rules={[{ required: true, message: '请输入实际完成数量' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入实际完成数量" />
          </Form.Item>
          <Form.Item
            name="rw_defect_qty"
            label="不良数量"
            rules={[{ required: true, message: '请输入不良数量' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入不良数量" />
          </Form.Item>
          <Form.Item name="rw_remark" label="备注">
            <Input placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
