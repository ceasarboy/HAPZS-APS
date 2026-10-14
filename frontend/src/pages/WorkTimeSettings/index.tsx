/**
 * V3.9 工作时间模式设置页面
 *
 * 支持配置不同日期类型的工作时间和休息时间：
 * - 周一到周五：8小时（常规）/ 10小时（加班）
 * - 周六周日：7小时
 * - 午休：11:45-12:45
 * - 晚饭（加班时）：14:30-15:00
 */
import { useState } from 'react';
import {
  Card, Table, Button, Modal, Form, Input, InputNumber, Switch,
  Space, message, Popconfirm, Tag, Typography, Divider,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getWorkTimePatterns, createWorkTimePattern, updateWorkTimePattern, deleteWorkTimePattern,
  type WorkTimePattern, type WorkPeriod, type BreakPeriod,
} from '../../api/workTime';

const { Text, Title } = Typography;

const dayTypeColors: Record<string, string> = {
  weekday_normal: 'blue',
  weekday_overtime: 'orange',
  weekend: 'purple',
};

const dayTypeLabels: Record<string, string> = {
  weekday_normal: '工作日(常规)',
  weekday_overtime: '工作日(加班)',
  weekend: '周末',
};

const WorkTimeSettings: React.FC = () => {
  const queryClient = useQueryClient();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  const { data: patterns, isLoading } = useQuery({
    queryKey: ['work-time-patterns'],
    queryFn: getWorkTimePatterns,
  });

  const createMutation = useMutation({
    mutationFn: createWorkTimePattern,
    onSuccess: () => {
      message.success('创建成功');
      queryClient.invalidateQueries({ queryKey: ['work-time-patterns'] });
      setModalVisible(false);
    },
    onError: (err) => message.error(`创建失败: ${err}`),
  });

  const updateMutation = useMutation({
    mutationFn: (data: { id: string; data: Partial<WorkTimePattern> }) =>
      updateWorkTimePattern(data.id, data.data),
    onSuccess: () => {
      message.success('更新成功');
      queryClient.invalidateQueries({ queryKey: ['work-time-patterns'] });
      setModalVisible(false);
    },
    onError: (err) => message.error(`更新失败: ${err}`),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteWorkTimePattern,
    onSuccess: () => {
      message.success('删除成功');
      queryClient.invalidateQueries({ queryKey: ['work-time-patterns'] });
    },
    onError: (err) => message.error(`删除失败: ${err}`),
  });

  const handleAdd = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({
      slot_duration_minutes: 15,
      is_active: true,
      work_periods: [{ start: '08:00', end: '11:45' }, { start: '12:45', end: '17:15' }],
      break_periods: [{ start: '11:45', end: '12:45', type: 'lunch' }],
    });
    setModalVisible(true);
  };

  const handleEdit = (record: WorkTimePattern) => {
    setEditingId(record.id);
    form.setFieldsValue(record);
    setModalVisible(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (editingId) {
        updateMutation.mutate({ id: editingId, data: values });
      } else {
        createMutation.mutate(values);
      }
    } catch (err) {
      // 验证失败
    }
  };

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id);
  };

  const formatPeriods = (periods: WorkPeriod[] | undefined) => {
    if (!periods || periods.length === 0) return '-';
    return periods.map(p => `${p.start}-${p.end}`).join(' | ');
  };

  const formatBreaks = (breaks: BreakPeriod[] | undefined) => {
    if (!breaks || breaks.length === 0) return '-';
    return breaks.map(b => `${b.start}-${b.end}(${b.type})`).join(' | ');
  };

  const columns = [
    {
      title: '模式编号',
      dataIndex: 'pattern_code',
      key: 'pattern_code',
      width: 180,
    },
    {
      title: '模式名称',
      dataIndex: 'pattern_name',
      key: 'pattern_name',
      width: 160,
    },
    {
      title: '日期类型',
      dataIndex: 'day_type',
      key: 'day_type',
      width: 120,
      render: (dayType: string) => (
        <Tag color={dayTypeColors[dayType] || 'default'}>
          {dayTypeLabels[dayType] || dayType}
        </Tag>
      ),
    },
    {
      title: '工时(小时)',
      dataIndex: 'work_hours',
      key: 'work_hours',
      width: 100,
      render: (v: number) => v ? `${v}h` : '-',
    },
    {
      title: '时间槽粒度',
      dataIndex: 'slot_duration_minutes',
      key: 'slot_duration_minutes',
      width: 100,
      render: (v: number) => v ? `${v}分钟` : '-',
    },
    {
      title: '工作时段',
      dataIndex: 'work_periods',
      key: 'work_periods',
      render: (periods: WorkPeriod[]) => (
        <Text style={{ fontSize: 12 }}>{formatPeriods(periods)}</Text>
      ),
    },
    {
      title: '休息时段',
      dataIndex: 'break_periods',
      key: 'break_periods',
      render: (breaks: BreakPeriod[]) => (
        <Text style={{ fontSize: 12 }}>{formatBreaks(breaks)}</Text>
      ),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '禁用'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: WorkTimePattern) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除此工作时间模式吗？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="工作时间模式设置"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新增模式
          </Button>
        }
      >
        <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
          <Title level={5} style={{ margin: 0 }}>说明</Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            工作时间模式用于排产时生成时间槽。系统根据日期类型自动选择对应模式：
            <br />
            - 周一到周五使用"工作日(常规)"或"工作日(加班)"模式
            <br />
            - 周六周日使用"周末"模式
            <br />
            - 时间槽粒度建议15分钟（对齐11:45休息时间）
            <br />
            - 休息时段不会生成时间槽，任务不会排在休息时间
          </Text>
        </div>

        <Table
          columns={columns}
          dataSource={patterns}
          rowKey="id"
          loading={isLoading}
          pagination={false}
          size="middle"
        />
      </Card>

      <Modal
        title={editingId ? '编辑工作时间模式' : '新增工作时间模式'}
        open={modalVisible}
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        width={700}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="pattern_code" label="模式编号" rules={[{ required: true, message: '请输入模式编号' }]}>
            <Input placeholder="如: WTP-WEEKDAY-NORMAL" />
          </Form.Item>
          <Form.Item name="pattern_name" label="模式名称" rules={[{ required: true, message: '请输入模式名称' }]}>
            <Input placeholder="如: 工作日(常规8小时)" />
          </Form.Item>
          <Form.Item name="day_type" label="日期类型" rules={[{ required: true, message: '请选择日期类型' }]}>
            <Input placeholder="如: weekday_normal / weekday_overtime / weekend" />
          </Form.Item>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="work_hours" label="工时(小时)" style={{ width: 200 }}>
              <InputNumber min={1} max={24} step={0.5} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="slot_duration_minutes" label="时间槽粒度(分钟)" style={{ width: 200 }}>
              <InputNumber min={5} max={60} step={5} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>

          <Divider>工作时段</Divider>
          <Text type="secondary" style={{ fontSize: 12 }}>
            工作时段：任务可以在这些时段内排产。格式：HH:MM
          </Text>
          <Form.List name="work_periods">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                    <Form.Item {...restField} name={[name, 'start']} rules={[{ required: true, message: '开始时间' }]}>
                      <Input placeholder="08:00" style={{ width: 100 }} />
                    </Form.Item>
                    <Text>至</Text>
                    <Form.Item {...restField} name={[name, 'end']} rules={[{ required: true, message: '结束时间' }]}>
                      <Input placeholder="11:45" style={{ width: 100 }} />
                    </Form.Item>
                    <Button type="link" danger onClick={() => remove(name)}>删除</Button>
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>
                  添加工作时段
                </Button>
              </>
            )}
          </Form.List>

          <Divider>休息时段</Divider>
          <Text type="secondary" style={{ fontSize: 12 }}>
            休息时段：任务不会排在这些时段内。如午休11:45-12:45、晚饭14:30-15:00
          </Text>
          <Form.List name="break_periods">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                    <Form.Item {...restField} name={[name, 'start']} rules={[{ required: true, message: '开始时间' }]}>
                      <Input placeholder="11:45" style={{ width: 100 }} />
                    </Form.Item>
                    <Text>至</Text>
                    <Form.Item {...restField} name={[name, 'end']} rules={[{ required: true, message: '结束时间' }]}>
                      <Input placeholder="12:45" style={{ width: 100 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'type']} rules={[{ required: true, message: '类型' }]}>
                      <Input placeholder="lunch" style={{ width: 100 }} />
                    </Form.Item>
                    <Button type="link" danger onClick={() => remove(name)}>删除</Button>
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ type: 'lunch' })} block icon={<PlusOutlined />}>
                  添加休息时段
                </Button>
              </>
            )}
          </Form.List>

          <Form.Item name="description" label="描述" style={{ marginTop: 16 }}>
            <Input.TextArea rows={2} placeholder="模式说明" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default WorkTimeSettings;
