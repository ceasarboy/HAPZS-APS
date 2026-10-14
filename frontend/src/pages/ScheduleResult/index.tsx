/** 派工单页面 - 含确认排产按钮和状态 Tag 着色 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Table, Button, Space, Modal, Form, Input, InputNumber,
  Segmented,
  Select, DatePicker, Switch, message, Popconfirm, Tag, Tooltip,
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  SyncOutlined, CloudUploadOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { FieldConfig } from '../../types/crud';
import type { PaginatedResponse, SyncStatus } from '../../types/crud';
import apiClient from '../../api/client';
import { confirmSchedule } from '../../api/result';
import { tableRegistry } from '../../config/tables';
import type { TableKey } from '../../config/tables';

/** 关联表名称字段映射 */
const RELATION_LABEL_MAP: Record<string, string> = {
  'products': 'prod_name',
  'process-info': 'proc_name',
  'production-lines': 'line_name',
  'material-masters': 'mat_name',
  'demand-plans': 'dp_code',
  'schedule-plans': 'sp_name',
  'schedule-results': 'plan_id',
};

/** 关联表API端点映射 */
const RELATION_ENDPOINT_MAP: Record<string, string> = {
  'products': '/products',
  'process-info': '/process-info',
  'production-lines': '/production-lines',
  'material-masters': '/material-masters',
  'demand-plans': '/demand-plans',
  'schedule-plans': '/schedule-plans',
  'schedule-results': '/schedule-results',
};

/** 同步状态标签颜色映射 */
const syncStatusColors: Record<SyncStatus, string> = {
  synced: 'green',
  pending_create: 'blue',
  pending_update: 'orange',
  pending_delete: 'red',
};

const syncStatusLabels: Record<SyncStatus, string> = {
  synced: '已同步',
  pending_create: '待创建',
  pending_update: '待更新',
  pending_delete: '待删除',
};

/** 排产状态 Tag 颜色映射 */
const srStatusColorMap: Record<string, string> = {
  '待确认': 'orange',
  '待生产': 'blue',
  '已完成': 'green',
  '已锁定': 'purple',
  '已失效': 'default',
};

/** 根据字段配置渲染表单项 */
function renderFormItem(field: FieldConfig) {
  const commonProps = {
    placeholder: field.placeholder || `请输入${field.label}`,
  };

  switch (field.type) {
    case 'number':
      return <InputNumber {...commonProps} style={{ width: '100%' }} />;
    case 'select':
      return <Select {...commonProps} options={field.options} allowClear />;
    case 'date':
      return <DatePicker {...commonProps} style={{ width: '100%' }} />;
    case 'boolean':
      return <Switch checkedChildren="是" unCheckedChildren="否" />;
    case 'textarea':
      return <Input.TextArea {...commonProps} rows={3} />;
    default:
      return <Input {...commonProps} />;
  }
}

/** 根据字段配置渲染表格单元格 */
function renderCellValue(field: FieldConfig, value: any) {
  if (value === null || value === undefined) return '-';
  switch (field.type) {
    case 'boolean':
      return value ? '是' : '否';
    case 'select':
      if (field.options) {
        const opt = field.options.find(o => o.value === value);
        return opt ? opt.label : value;
      }
      return value;
    case 'date':
      return typeof value === 'string' ? value.split('T')[0] : value;
    default:
      return value;
  }
}

export default function ScheduleResultPage() {
  const config = tableRegistry['schedule-results' as TableKey];
  const { title, fields, api } = config;

  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<any>(null);
  const [form] = Form.useForm();
  const [syncing, setSyncing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [selectedPlanId, setSelectedPlanId] = useState<string>('');
  const [sortMode, setSortMode] = useState<'time' | 'order'>('time');

  // 关联表数据缓存
  const [relationCache, setRelationCache] = useState<Record<string, Record<string, string>>>({});

  /** 加载关联表数据 */
  const loadRelationData = useCallback(async () => {
    const relationFields = fields.filter(f => f.isRelation && f.relationTable);
    const tablesToLoad = [...new Set(relationFields.map(f => f.relationTable!))];

    const newCache: Record<string, Record<string, string>> = {};
    for (const tableKey of tablesToLoad) {
      if (relationCache[tableKey]) {
        newCache[tableKey] = relationCache[tableKey];
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
      } catch {
        newCache[tableKey] = {};
      }
    }
    if (Object.keys(newCache).length > 0) {
      setRelationCache(prev => ({ ...prev, ...newCache }));
    }
  }, [fields, relationCache]);

  /** 获取关联名称 */
  const getRelationLabel = useCallback((tableKey: string, id: string): string => {
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
      const res: PaginatedResponse<any> = await api.getList({ skip, limit: pageSize });
      setData(res.items);
      setTotal(res.total);

      // 自动提取可用的 plan_id 列表
      const planIds = [...new Set(res.items.map((item: any) => item.plan_id).filter(Boolean))];
      if (planIds.length === 1) {
        setSelectedPlanId(planIds[0]);
      }
    } catch {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, [api, page, pageSize]);

  /** 排序后的数据 */
  const sortedData = useMemo(() => {
    const sorted = [...data];
    if (sortMode === 'order') {
      sorted.sort((a, b) => {
        const ka = (a.demand_id || '') + '|' + (a.sr_date || '') + (a.sr_time_slot || '');
        const kb = (b.demand_id || '') + '|' + (b.sr_date || '') + (b.sr_time_slot || '');
        return ka.localeCompare(kb);
      });
    } else {
      sorted.sort((a, b) => {
        const ka = (a.sr_date || '') + (a.sr_time_slot || '');
        const kb = (b.sr_date || '') + (b.sr_time_slot || '');
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

  /** 新增 */
  const handleCreate = () => {
    setEditingRecord(null);
    form.resetFields();
    setModalOpen(true);
  };

  /** 编辑 */
  const handleEdit = (record: any) => {
    setEditingRecord(record);
    const formValues: Record<string, any> = {};
    fields.forEach(f => {
      if (f.type === 'boolean') {
        formValues[f.name] = record[f.name] ?? false;
      } else if (f.type === 'date' && record[f.name]) {
        formValues[f.name] = record[f.name];
      } else {
        formValues[f.name] = record[f.name] ?? undefined;
      }
    });
    form.setFieldsValue(formValues);
    setModalOpen(true);
  };

  /** 删除 */
  const handleDelete = async (id: string) => {
    try {
      await api.remove(id);
      message.success('删除成功');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

  /** 提交表单 */
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      fields.forEach(f => {
        if (f.type === 'date' && values[f.name]) {
          values[f.name] = values[f.name].format?.('YYYY-MM-DD') ?? values[f.name];
        }
      });

      if (editingRecord) {
        await api.update(editingRecord.id, values);
        message.success('更新成功');
      } else {
        await api.create(values);
        message.success('创建成功');
      }
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (err: any) {
      if (err.errorFields) return;
      message.error(editingRecord ? '更新失败' : '创建失败');
    }
  };

  /** 同步到HAP */
  const handleSync = async () => {
    setSyncing(true);
    try {
      await apiClient.post('/sync/push-all');
      message.success('同步任务已提交');
      setTimeout(() => fetchData(), 2000);
    } catch {
      message.error('同步失败');
    } finally {
      setSyncing(false);
    }
  };

  /** 从HAP拉取 */
  const handlePull = async () => {
    setSyncing(true);
    try {
      await apiClient.post('/sync/pull-all');
      message.success('拉取任务已提交');
      setTimeout(() => fetchData(), 3000);
    } catch {
      message.error('拉取失败');
    } finally {
      setSyncing(false);
    }
  };

  /** 确认排产 */
  const handleConfirm = async () => {
    if (!selectedPlanId) {
      message.warning('请输入方案ID');
      return;
    }
    setConfirming(true);
    try {
      await confirmSchedule(selectedPlanId);
      message.success('排产确认成功');
      fetchData();
    } catch {
      message.error('排产确认失败');
    } finally {
      setConfirming(false);
    }
  };

  /** 构建表格列 */
  const columns: ColumnsType<any> = [
    {
      title: '序号',
      width: 50,
      render: (_, __, idx) => (page - 1) * pageSize + idx + 1,
      fixed: 'left',
    },
    ...fields
      .filter(f => f.showInTable !== false)
      .map((f): ColumnsType<any>[number] => {
        if (f.name === 'sr_status') {
          return {
            title: f.label,
            dataIndex: f.name,
            key: f.name,
            width: f.width || 80,
            render: (val: string) => {
              if (!val) return '-';
              return <Tag color={srStatusColorMap[val] || 'default'}>{val}</Tag>;
            },
          };
        }
        return {
          title: f.label,
          dataIndex: f.name,
          key: f.name,
          width: f.width || 120,
          ellipsis: true,
          render: (val: any) => {
            if (f.isRelation && f.relationTable) {
              const label = getRelationLabel(f.relationTable, val);
              return (
                <Tooltip title={`ID: ${val}`}>
                  <Tag color="blue">{label}</Tag>
                </Tooltip>
              );
            }
            return renderCellValue(f, val);
          },
        };
      }),
    {
      title: '同步状态',
      dataIndex: 'sync_status',
      key: 'sync_status',
      width: 90,
      render: (val: SyncStatus) => val ? (
        <Tag color={syncStatusColors[val]}>{syncStatusLabels[val]}</Tag>
      ) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)} okText="确认" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  /** 构建表单字段 */
  const formFields = fields.filter(f => f.showInForm !== false);

  // 提取去重的 plan_id 列表供选择
  const planIdOptions = [...new Set(data.map((item: any) => item.plan_id).filter(Boolean))].map(id => ({
    label: id,
    value: id,
  }));

  return (
    <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: 12, padding: 20, backdropFilter: 'blur(8px)' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1E3A8A' }}>{title}</h2>
        <Space>
          <Select
            value={selectedPlanId || undefined}
            onChange={setSelectedPlanId}
            placeholder="选择方案ID"
            style={{ width: 220 }}
            showSearch
            allowClear
            options={planIdOptions}
          />
          <Popconfirm
            title="确认排产"
            description={`确认方案 ${selectedPlanId || ''} 的排产结果？`}
            onConfirm={handleConfirm}
            okText="确认"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={confirming}
              disabled={!selectedPlanId}
            >
              确认排产
            </Button>
          </Popconfirm>
          <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          <Button icon={<CloudUploadOutlined />} onClick={handlePull} loading={syncing}>从HAP拉取</Button>
          <Button icon={<SyncOutlined />} onClick={handleSync} loading={syncing}>同步到HAP</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增</Button>
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

      {/* 新增/编辑弹窗 */}
      <Modal
        title={editingRecord ? `编辑${title}` : `新增${title}`}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        width={600}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ maxHeight: '60vh', overflowY: 'auto', paddingRight: 8 }}>
          {formFields.map(f => (
            <Form.Item
              key={f.name}
              name={f.name}
              label={f.label}
              valuePropName={f.type === 'boolean' ? 'checked' : 'value'}
              rules={f.required && !editingRecord ? [{ required: true, message: `请输入${f.label}` }] : undefined}
            >
              {renderFormItem(f)}
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </div>
  );
}
