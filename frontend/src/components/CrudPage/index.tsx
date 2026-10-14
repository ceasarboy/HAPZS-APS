/** 通用 CRUD 页面组件 - 数据驱动的增删改查界面 */

import { useState, useEffect, useCallback } from 'react';
import dayjs from 'dayjs';
import {
  Table, Button, Space, Modal, Form, Input, InputNumber,
  Select, DatePicker, Switch, message, Popconfirm, Tag, Tooltip,
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  SyncOutlined, CloudUploadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { FieldConfig, TableConfig } from '../../types/crud';
import type { PaginatedResponse, SyncStatus } from '../../types/crud';
import apiClient from '../../api/client';

/** 关联表名称字段映射：tableKey → 显示字段名 */
const RELATION_LABEL_MAP: Record<string, string> = {
  'products': 'prod_code',
  'process-info': 'proc_name',
  'production-lines': 'line_name',
  'material-masters': 'mat_name',
  'demand-plans': 'dp_code',
  'schedule-plans': 'sp_name',
  'schedule-results': 'plan_id',
};

/** 关联表组合显示字段：tableKey → [编码字段, 名称字段]，用于"编码 - 名称"组合显示 */
const RELATION_COMPOSITE_MAP: Record<string, [string, string]> = {
  'products': ['prod_code', 'prod_name'],
  'process-info': ['proc_code', 'proc_name'],
  'production-lines': ['line_code', 'line_name'],
  'material-masters': ['mat_code', 'mat_name'],
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

interface CrudPageProps {
  config: TableConfig<any, any, any>;
}

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

/** 根据字段配置渲染表单项 */
function renderFormItem(
  field: FieldConfig,
  relationData?: Record<string, Record<string, string>>,
) {
  const commonProps = {
    placeholder: field.placeholder || `请输入${field.label}`,
  };

  // 关联字段渲染为下拉选择
  if (field.isRelation && field.relationTable && relationData) {
    const cache = relationData[field.relationTable] || {};
    const options = Object.entries(cache).map(([id, label]) => ({
      value: id,
      label,
    }));
    return (
      <Select
        {...commonProps}
        options={options}
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder={`请选择${field.label}`}
      />
    );
  }

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

export default function CrudPage({ config }: CrudPageProps) {
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
  const [hoveredRecord, setHoveredRecord] = useState<any>(null);

  // 关联表数据缓存: tableKey → { id: label }
  const [relationCache, setRelationCache] = useState<Record<string, Record<string, string>>>({});

  // 筛选状态
  const [filterValue, setFilterValue] = useState<string | undefined>(undefined);

  // 查找可筛选字段和默认排序字段
  const filterableFields = fields.filter(f => f.filterable);
  const defaultSortField = fields.find(f => f.defaultSort);

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
        const composite = RELATION_COMPOSITE_MAP[tableKey];
        const map: Record<string, string> = {};
        for (const item of items) {
          if (composite) {
            // 组合显示："编码 - 名称"
            const code = item[composite[0]] || '';
            const name = item[composite[1]] || '';
            map[item.id] = code && name ? `${code} - ${name}` : (code || name || item.id);
          } else {
            map[item.id] = item[labelField] || item.id;
          }
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
      const params: import('../types/crud').PaginationParams = { skip, limit: pageSize };
      // 应用筛选
      if (filterableFields.length > 0 && filterValue) {
        params.filter_field = filterableFields[0].name;
        params.filter_value = filterValue;
      }
      // 应用默认排序
      if (defaultSortField && defaultSortField.defaultSort) {
        params.sort_field = defaultSortField.name;
        params.sort_order = defaultSortField.defaultSort;
      }
      const res: PaginatedResponse<any> = await api.getList(params);
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, [api, page, pageSize, filterValue, filterableFields, defaultSortField]);

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
        // DatePicker 需要 dayjs 对象，不能直接传字符串
        formValues[f.name] = dayjs(record[f.name]);
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

  /** 提交表单（新增/编辑） */
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      fields.forEach(f => {
        if (f.type === 'date' && values[f.name]) {
          values[f.name] = values[f.name].format?.('YYYY-MM-DD') ?? values[f.name];
        }
        // 自动生成编码字段（新增时）
        if (f.autoGenerate && !editingRecord && !values[f.name]) {
          const now = new Date();
          const pad = (n: number) => String(n).padStart(2, '0');
          const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
          const rand = Math.random().toString(36).substring(2, 6).toUpperCase();
          const prefix = f.autoGeneratePrefix || 'AUTO';
          values[f.name] = `${prefix}-${ts}-${rand}`;
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

  /** 构建行浮动框内容 */
  const buildRowPopover = (record: any) => {
    const rows = fields
      .filter(f => record[f.name] !== null && record[f.name] !== undefined && record[f.name] !== '')
      .map(f => {
        let val = record[f.name];
        if (f.isRelation && f.relationTable) {
          const label = getRelationLabel(f.relationTable, val);
          val = label;
        } else {
          val = renderCellValue(f, val);
        }
        return { label: f.label, value: val };
      });
    return (
      <div style={{ maxWidth: 400 }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, padding: '2px 0', fontSize: 12 }}>
            <span style={{ color: '#666', minWidth: 80, flexShrink: 0 }}>{r.label}:</span>
            <span style={{ color: '#333', wordBreak: 'break-all' }}>{String(r.value)}</span>
          </div>
        ))}
      </div>
    );
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
      .map((f): ColumnsType<any>[number] => ({
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
      })),
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

  return (
    <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: 12, padding: 20, backdropFilter: 'blur(8px)' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1E3A8A' }}>{title}</h2>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          <Button icon={<CloudUploadOutlined />} onClick={handlePull} loading={syncing}>从HAP拉取</Button>
          <Button icon={<SyncOutlined />} onClick={handleSync} loading={syncing}>同步到HAP</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增</Button>
        </Space>
      </div>

      {/* 筛选栏 */}
      {filterableFields.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12, gap: 8 }}>
          <span style={{ fontSize: 13, color: '#666' }}>按{filterableFields[0].label}筛选:</span>
          <Select
            style={{ width: 280 }}
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部"
            value={filterValue}
            onChange={(val) => {
              setFilterValue(val);
              setPage(1);
            }}
            options={filterableFields[0].relationTable && relationCache[filterableFields[0].relationTable!]
              ? Object.entries(relationCache[filterableFields[0].relationTable!]).map(([id, label]) => ({ value: id, label }))
              : []
            }
          />
        </div>
      )}

      {/* 数据表格 */}
      <div style={{ position: 'relative' }}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 'max-content' }}
          size="small"
          onRow={(record) => ({
            onMouseEnter: () => setHoveredRecord(record),
            onMouseLeave: () => setHoveredRecord(null),
          })}
          rowClassName={() => 'crud-row'}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
        />
        {/* 行 hover 浮动框 */}
        {hoveredRecord && (
          <div style={{
            position: 'fixed',
            right: 24,
            top: 120,
            zIndex: 1000,
            background: '#fff',
            border: '1px solid #e8e8e8',
            borderRadius: 8,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            padding: '12px 16px',
            maxWidth: 400,
            maxHeight: '60vh',
            overflowY: 'auto',
          }}>
            <div style={{ fontWeight: 600, marginBottom: 8, color: '#1E3A8A', fontSize: 14 }}>{title} 详情</div>
            {buildRowPopover(hoveredRecord)}
          </div>
        )}
      </div>

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
              {renderFormItem(f, relationCache)}
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </div>
  );
}
