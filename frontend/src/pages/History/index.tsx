import { useState } from 'react';
import { Card, Table, Tag, Modal, Descriptions, Spin, Button, Tabs } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { getScheduleList, cancelSchedule } from '../../api/schedule';
import { getResult } from '../../api/result';
import type { ScheduleListItem } from '../../types/schedule';
import type { ScheduleResult } from '../../types/result';
import PlanMatrix from '../../components/PlanMatrix';
import LoadChart from '../../components/LoadChart';
import GanttChart from '../../components/GanttChart';
import ProcessFlow from '../../components/ProcessFlow';
import { message } from 'antd';

/** 排产历史页面 */
const History: React.FC = () => {
  const [detailVisible, setDetailVisible] = useState(false);
  const [currentRecord, setCurrentRecord] = useState<ScheduleListItem | null>(null);
  const [resultDetail, setResultDetail] = useState<ScheduleResult | null>(null);
  const [resultLoading, setResultLoading] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['scheduleList'],
    queryFn: async () => {
      const res = await getScheduleList();
      const raw = res.data;
      // 后端返回 {items: [], total: 0} 或直接数组
      if (Array.isArray(raw)) return raw as ScheduleListItem[];
      return ((raw as Record<string, unknown>)?.items ?? []) as ScheduleListItem[];
    },
  });

  /** 状态标签颜色映射 */
  const statusColorMap: Record<string, string> = {
    PENDING: 'default',
    RUNNING: 'processing',
    SUCCESS: 'success',
    FAILED: 'error',
  };

  /** 状态文本映射 */
  const statusTextMap: Record<string, string> = {
    PENDING: '等待中',
    RUNNING: '运行中',
    SUCCESS: '成功',
    FAILED: '失败',
  };

  /** 查看排产结果详情 */
  const handleViewDetail = async (record: ScheduleListItem) => {
    setCurrentRecord(record);
    setDetailVisible(true);
    setResultDetail(null);

    if (record.status === 'SUCCESS') {
      setResultLoading(true);
      try {
        const res = await getResult(record.task_id);
        setResultDetail(res.data);
      } catch {
        message.error('获取排产结果失败');
      } finally {
        setResultLoading(false);
      }
    }
  };

  /** 取消排产 */
  const handleCancel = async (taskId: string) => {
    try {
      await cancelSchedule(taskId);
      message.success('已取消排产');
    } catch {
      message.error('取消排产失败');
    }
  };

  // 列定义
  const columns: ColumnsType<ScheduleListItem> = [
    {
      title: '任务ID',
      dataIndex: 'task_id',
      key: 'task_id',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={statusColorMap[status]}>{statusTextMap[status] || status}</Tag>
      ),
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      render: (progress: number) => `${progress}%`,
    },
    {
      title: '求解状态',
      key: 'solve_status',
      render: (_: unknown, record: ScheduleListItem) =>
        record.result_summary?.solve_status || '-',
    },
    {
      title: '任务数量',
      key: 'task_count',
      render: (_: unknown, record: ScheduleListItem) =>
        record.result_summary?.task_count ?? '-',
    },
    {
      title: '求解耗时',
      key: 'solve_time',
      render: (_: unknown, record: ScheduleListItem) =>
        record.result_summary ? `${record.result_summary.solve_time_seconds}s` : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text?: string) => text || '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: ScheduleListItem) => (
        <Button
          type="link"
          danger={record.status === 'RUNNING'}
          onClick={(e) => {
            e.stopPropagation();
            if (record.status === 'RUNNING') {
              handleCancel(record.task_id);
            } else {
              handleViewDetail(record);
            }
          }}
        >
          {record.status === 'RUNNING' ? '取消' : '查看'}
        </Button>
      ),
    },
  ];

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" spinning tip="加载排产历史...">
          <div style={{ minHeight: 200 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div>
      <Card title="排产历史">
        <Table
          columns={columns}
          dataSource={data ?? []}
          rowKey="task_id"
          onRow={(record) => ({
            onClick: () => handleViewDetail(record),
            style: { cursor: 'pointer' },
          })}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title="排产任务详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={1200}
      >
        {currentRecord && (
          <>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="任务ID">{currentRecord.task_id}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusColorMap[currentRecord.status]}>
                  {statusTextMap[currentRecord.status]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="进度">{currentRecord.progress}%</Descriptions.Item>
              {currentRecord.result_summary && (
                <>
                  <Descriptions.Item label="计划ID">{currentRecord.result_summary.plan_id}</Descriptions.Item>
                  <Descriptions.Item label="求解状态">{currentRecord.result_summary.solve_status}</Descriptions.Item>
                  <Descriptions.Item label="任务数量">{currentRecord.result_summary.task_count}</Descriptions.Item>
                  <Descriptions.Item label="求解耗时">{currentRecord.result_summary.solve_time_seconds}s</Descriptions.Item>
                  <Descriptions.Item label="求解器">{currentRecord.result_summary.solver_name}</Descriptions.Item>
                </>
              )}
            </Descriptions>

            {resultLoading && <Spin spinning tip="加载排产结果..."><div style={{minHeight:100}} /></Spin>}
            {resultDetail && (
              <Tabs
                defaultActiveKey="gantt"
                items={[
                  {
                    key: 'flow',
                    label: '工艺流程图',
                    children: <ProcessFlow height={400} />,
                  },
                  {
                    key: 'gantt',
                    label: '排产甘特图',
                    children: <GanttChart data={resultDetail} height={400} />,
                  },
                  {
                    key: 'matrix',
                    label: '计划矩阵',
                    children: <PlanMatrix data={resultDetail} />,
                  },
                  {
                    key: 'load',
                    label: '负荷率分析',
                    children: <LoadChart loadRates={resultDetail.loadRates} />,
                  },
                ]}
              />
            )}
          </>
        )}
      </Modal>
    </div>
  );
};

export default History;
