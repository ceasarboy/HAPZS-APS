import { useState } from 'react';
import { Table, Modal, InputNumber, Form, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ScheduleResult, PlanCell } from '../../types/result';

/** 计划矩阵组件属性 */
interface PlanMatrixProps {
  /** 排产结果数据 */
  data: ScheduleResult;
  /** 单元格变更回调 */
  onCellChange?: (workcenterCode: string, cell: PlanCell, newQuantity: number) => void;
  /** 冻结时段列表 */
  frozenTimes?: string[];
}

/** 编辑表单值 */
interface EditFormValues {
  quantity: number;
}

/** 约束类型颜色映射 */
const constraintTypeColor: Record<string, string> = {
  '机时约束': '#1890ff',
  '人员工时约束': '#52c41a',
};

/** seq → 背景色映射（并行工序同 seq 同色） */
const seqBgColor: Record<number, string> = {
  1: '#e6f7ff',
  2: '#f6ffed',
  3: '#fff7e6',  // 并行组高亮
  4: '#f9f0ff',
  5: '#e6fffb',
  6: '#fff1f0',
  7: '#fffbe6',
};

/** seq → 左边框颜色映射 */
const seqBorderColor: Record<number, string> = {
  1: '#1890ff',
  2: '#52c41a',
  3: '#fa8c16',  // 并行组橙色边框
  4: '#722ed1',
  5: '#13c2c2',
  6: '#f5222d',
  7: '#faad14',
};

/** 优先级 → Tag 颜色映射 */
const priorityColor: Record<string, string> = {
  '紧急': 'red',
  '高': 'orange',
  '中': 'default',
  '低': 'default',
};

/** 计划矩阵组件：以表格形式展示排产结果 */
const PlanMatrix: React.FC<PlanMatrixProps> = ({ data, onCellChange, frozenTimes = [] }) => {
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingCell, setEditingCell] = useState<{ workcenterCode: string; cell: PlanCell } | null>(null);
  const [form] = Form.useForm<EditFormValues>();

  // 收集所有时间段（去重排序），防御性处理空数据
  const workcenterPlans = data?.workcenterPlans ?? [];
  const allTimeSlots = Array.from(
    new Set(workcenterPlans.flatMap((wp) => (wp.cells ?? []).map((c) => c.timeSlot)))
  ).sort();

  // 构建列定义
  const columns: ColumnsType<Record<string, unknown>> = [
    {
      title: '时间段',
      dataIndex: 'timeSlot',
      key: 'timeSlot',
      fixed: 'left',
      width: 140,
      render: (text: string) => {
        const isFrozen = frozenTimes.includes(text);
        return (
          <span style={{ color: isFrozen ? '#999' : undefined, fontSize: 12 }}>
            {text}
            {isFrozen && <Tag color="default" style={{ marginLeft: 4 }}>冻结</Tag>}
          </span>
        );
      },
    },
    ...workcenterPlans.map((wp) => ({
      title: wp.workcenterName,
      dataIndex: wp.workcenterCode,
      key: wp.workcenterCode,
      width: 160,
      render: (_: unknown, record: Record<string, unknown>) => {
        const cells = record[wp.workcenterCode] as PlanCell[] | undefined;
        if (!cells || cells.length === 0) return '-';
        const isFrozen = cells[0].frozen || frozenTimes.includes(cells[0].timeSlot);
        return (
          <div
            style={{
              cursor: isFrozen ? 'not-allowed' : 'pointer',
              background: isFrozen ? '#f5f5f5' : undefined,
              padding: '4px 8px',
              borderRadius: 4,
            }}
            onClick={() => {
              if (!isFrozen && cells.length === 1) {
                setEditingCell({ workcenterCode: wp.workcenterCode, cell: cells[0] });
                form.setFieldsValue({ quantity: cells[0].quantity });
                setEditModalVisible(true);
              }
            }}
          >
            {cells.map((cell, idx) => {
              const seq = cell.seq ?? 0;
              const bgColor = seqBgColor[seq] || '#fafafa';
              const borderColor = seqBorderColor[seq] || '#d9d9d9';
              // 检测并行：同一单元格内同 seq 的工序有多个
              const sameSeqCount = cells.filter((c) => (c.seq ?? 0) === seq).length;
              const isParallel = sameSeqCount > 1;
              return (
                <div
                  key={idx}
                  style={{
                    marginTop: idx > 0 ? 4 : 0,
                    paddingTop: idx > 0 ? 4 : 0,
                    borderTop: idx > 0 ? '1px dashed #e8e8e8' : undefined,
                    background: bgColor,
                    borderLeft: `3px solid ${borderColor}`,
                    padding: '4px 8px',
                    borderRadius: 2,
                  }}
                >
                  <div style={{ fontWeight: 500, fontSize: 13 }}>
                    {cell.productName || '-'}
                    {cell.priority && (cell.priority === '紧急' || cell.priority === '高') && (
                      <Tag color={priorityColor[cell.priority] || 'default'} style={{ marginLeft: 4, fontSize: 10 }}>
                        {cell.priority}
                      </Tag>
                    )}
                  </div>
                  {cell.processName && (
                    <div style={{ fontSize: 11, color: constraintTypeColor[cell.constraintType || ''] || '#888' }}>
                      {cell.processName}
                      {isParallel && (
                        <Tag color="orange" style={{ marginLeft: 4, fontSize: 10 }}>并行</Tag>
                      )}
                      {cell.dependencyType && cell.dependencyType !== 'FS' && (
                        <Tag color="blue" style={{ marginLeft: 4, fontSize: 10 }}>{cell.dependencyType}</Tag>
                      )}
                    </div>
                  )}
                  {((cell.waitTime ?? 0) > 0 || (cell.prepTime ?? 0) > 0) && (
                    <div style={{ fontSize: 10, color: '#999' }}>
                      {(cell.waitTime ?? 0) > 0 && `等待${cell.waitTime}min`}
                      {(cell.waitTime ?? 0) > 0 && (cell.prepTime ?? 0) > 0 && ' / '}
                      {(cell.prepTime ?? 0) > 0 && `准备${cell.prepTime}min`}
                    </div>
                  )}
                  <div style={{ fontSize: 12, color: '#888' }}>{cell.quantity}</div>
                </div>
              );
            })}
          </div>
        );
      },
    })),
  ];

  // 构建表格数据源（同一产线同一时段可能有多个工序任务）
  const dataSource = allTimeSlots.map((timeSlot) => {
    const row: Record<string, unknown> = { timeSlot, key: timeSlot };
    data.workcenterPlans?.forEach((wp) => {
      const cells = wp.cells.filter((c) => c.timeSlot === timeSlot);
      row[wp.workcenterCode] = cells.length > 0 ? cells : null;
    });
    return row;
  });

  /** 处理编辑确认 */
  const handleEditOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingCell && onCellChange) {
        onCellChange(editingCell.workcenterCode, editingCell.cell, values.quantity);
      }
      setEditModalVisible(false);
      setEditingCell(null);
    } catch {
      // 表单校验失败
    }
  };

  return (
    <>
      <Table
        columns={columns}
        dataSource={dataSource}
        pagination={false}
        scroll={{ x: 'max-content' }}
        size="small"
        bordered
      />

      {/* 编辑单元格弹窗 */}
      <Modal
        title="编辑计划"
        open={editModalVisible}
        onOk={handleEditOk}
        onCancel={() => {
          setEditModalVisible(false);
          setEditingCell(null);
        }}
      >
        {editingCell && (
          <Form form={form} layout="vertical">
            <Form.Item label="产品">
              <span>{editingCell.cell.productName}</span>
            </Form.Item>
            {editingCell.cell.processName && (
              <Form.Item label="工序">
                <span>{editingCell.cell.processName}</span>
                {editingCell.cell.constraintType && (
                  <Tag
                    color={constraintTypeColor[editingCell.cell.constraintType] || 'default'}
                    style={{ marginLeft: 8 }}
                  >
                    {editingCell.cell.constraintType}
                  </Tag>
                )}
              </Form.Item>
            )}
            <Form.Item
              name="quantity"
              label="数量"
              rules={[{ required: true, message: '请输入数量' }]}
            >
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </>
  );
};

export default PlanMatrix;
