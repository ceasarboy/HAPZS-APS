import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import {
  Form,
  DatePicker,
  Button,
  Spin,
  Progress,
  message,
  Row,
  Col,
  Space,
  Select,
  Descriptions,
  Tag,
  Tabs,
  InputNumber,
  Modal,
  Input,
} from 'antd';
import { PlayCircleOutlined, StopOutlined, PlusOutlined, CloudUploadOutlined, DownloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useScheduleStore } from '../../stores/scheduleStore';
import PlanMatrix from '../../components/PlanMatrix';
import LoadChart from '../../components/LoadChart';
import GanttChart from '../../components/GanttChart';
import ProcessFlow from '../../components/ProcessFlow';
import { createSchedule, getScheduleStatus, cancelSchedule, insertUrgentOrder } from '../../api/schedule';
import { getProducts } from '../../api/hap';
import type { ProductItem } from '../../api/hap';
import { getResult, getLatestResult, exportCsv, pushToHap, adjustPlan } from '../../api/result';
import type { PlanCell } from '../../types/result';
import type { SolverType, ResultSummary } from '../../types/schedule';

const { RangePicker } = DatePicker;

/** 排产编制页面 - Glassmorphism Cards + Tables */
const Schedule: React.FC = () => {
  const [form] = Form.useForm();
  const { scheduleStatus, progress, result, setTaskId, setScheduleStatus, setProgress, setResult, reset } =
    useScheduleStore();
  const [loading, setLoading] = useState(false);
  const [pushing, setPushing] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [resultSummary, setResultSummary] = useState<ResultSummary | undefined>(undefined);
  const [insertModalVisible, setInsertModalVisible] = useState(false);
  const [insertLoading, setInsertLoading] = useState(false);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [insertForm] = Form.useForm();

  // 派生数据：产品下拉选项，避免每次渲染重新计算 map
  const productOptions = useMemo(
    () => products.map((p) => ({ value: p.id, label: `${p.name} (${p.code})` })),
    [products]
  );

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // V3.9.1 页面初始加载最新排产结果，便于直接查看甘特图
  useEffect(() => {
    (async () => {
      try {
        const res = await getLatestResult();
        if (res.data?.workcenterPlans?.length) {
          setResult(res.data);
          setScheduleStatus('SUCCESS');
        }
      } catch {
        // 忽略：无最新结果时用户需手动触发排产
      }
    })();
  }, [setResult, setScheduleStatus]);

  const startPolling = useCallback((taskId: string) => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await getScheduleStatus(taskId);
        const data = res.data;
        setProgress(data.progress);
        setScheduleStatus(data.status);

        if (data.result_summary) {
          setResultSummary(data.result_summary);
        }

        if (data.status === 'SUCCESS') {
          stopPolling();
          const resultRes = await getResult(taskId);
          setResult(resultRes.data);
          setLoading(false);
          message.success('排产完成');
        } else if (data.status === 'FAILURE' || data.status === 'FAILED') {
          stopPolling();
          setLoading(false);
          const errMsg = data.result_summary?.error || '排产失败';
          message.error(errMsg);
        }
      } catch {
        stopPolling();
        setLoading(false);
        message.error('查询排产状态失败');
      }
    }, 2000);
  }, [stopPolling, setProgress, setScheduleStatus, setResult]);

  const handleStartSchedule = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      reset();
      setResultSummary(undefined);

      const [startTime, endTime] = values.timeRange;
      const requestData = {
        solver_type: values.solverType as SolverType,
        start_time: startTime.format('YYYY-MM-DDTHH:mm:ss'),
        end_time: endTime.format('YYYY-MM-DDTHH:mm:ss'),
        freeze_horizon: values.freezeHorizon ?? 0,
        solver_params: {
          scheduling_mode: 'time_exclusive',
          max_time_in_seconds: 120,
          num_workers: 4,
        },
      };

      const res = await createSchedule(requestData);
      const { task_id, status } = res.data;
      setTaskId(task_id);
      setScheduleStatus(status);
      setProgress(0);
      startPolling(task_id);
    } catch (err) {
      setLoading(false);
      if (err instanceof Error) {
        message.error(`排产请求失败: ${err.message}`);
      }
    }
  };

  const handleCancel = async () => {
    const { currentTaskId } = useScheduleStore.getState();
    if (!currentTaskId) return;
    try {
      stopPolling();
      await cancelSchedule(currentTaskId);
      setScheduleStatus('FAILED');
      setLoading(false);
      message.info('排产已取消');
    } catch {
      message.error('取消排产失败');
    }
  };

  const handleCellChange = useCallback(async (workcenterCode: string, cell: PlanCell, newQuantity: number) => {
    const { currentTaskId } = useScheduleStore.getState();
    if (!result || !currentTaskId) return;

    try {
      await adjustPlan(currentTaskId, {
        workcenterCode,
        timeSlot: cell.timeSlot,
        productCode: cell.productCode,
        quantity: newQuantity,
      });
      const newResult = { ...result };
      const plan = newResult.workcenterPlans.find((wp) => wp.workcenterCode === workcenterCode);
      if (plan) {
        const cellIndex = plan.cells.findIndex(
          (c) => c.timeSlot === cell.timeSlot && c.productCode === cell.productCode
        );
        if (cellIndex >= 0) {
          plan.cells[cellIndex] = { ...plan.cells[cellIndex], quantity: newQuantity };
        }
      }
      setResult(newResult);
      message.info(`已更新 ${cell.productName} 数量为 ${newQuantity}`);
    } catch {
      message.error('调整计划失败');
    }
  }, [result, setResult]);

  const handlePushToHap = async () => {
    const { currentTaskId } = useScheduleStore.getState();
    if (!currentTaskId) return;
    try {
      setPushing(true);
      await pushToHap(currentTaskId);
      message.success('已推送到 HAP');
    } catch {
      message.error('推送到 HAP 失败');
    } finally {
      setPushing(false);
    }
  };

  const handleExport = async () => {
    const { currentTaskId } = useScheduleStore.getState();
    if (!currentTaskId) return;
    try {
      const res = await exportCsv(currentTaskId);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `schedule_${currentTaskId}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      message.error('导出失败');
    }
  };

  const handleOpenInsert = async () => {
    setInsertModalVisible(true);
    try {
      const res = await getProducts();
      setProducts(res.data);
    } catch {
      message.error('加载产品列表失败');
    }
  };

  const handleSubmitInsert = async () => {
    try {
      const values = await insertForm.validateFields();
      setInsertLoading(true);
      const res = await insertUrgentOrder({
        product_id: values.productId,
        quantity: values.quantity,
        due_date: values.dueDate.format('YYYY-MM-DD'),
        remark: values.remark || '',
      });
      message.success(`紧急插单成功：${res.data.dp_code}，请重新排产`);
      setInsertModalVisible(false);
      insertForm.resetFields();
    } catch (err) {
      if (err instanceof Error) {
        message.error(`插单失败: ${err.message}`);
      }
    } finally {
      setInsertLoading(false);
    }
  };

  return (
    <div>
      {/* 排产参数 - Glass Card */}
      <div className="glass-card animate-fade-in" style={{ padding: 24, marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#1E3A8A', marginBottom: 16, letterSpacing: '-0.01em' }}>
          排产参数
        </div>
        <Form
          form={form}
          layout="inline"
          initialValues={{
            timeRange: [dayjs(), dayjs().add(7, 'day')],
            solverType: 'ortools',
          }}
        >
          <Form.Item name="timeRange" label="时间范围" rules={[{ required: true }]}>
            <RangePicker showTime />
          </Form.Item>
          <Form.Item name="solverType" label="求解器" rules={[{ required: true }]}>
            <Select style={{ width: 160 }}>
              <Select.Option value="ortools">OR-Tools (CP-SAT)</Select.Option>
              <Select.Option value="ga">遗传算法 (GA)</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="freezeHorizon" label="冻结窗口(天)" tooltip="前 N 天的时间槽被锁定，不允许新任务分配">
            <InputNumber min={0} max={7} style={{ width: 120 }} placeholder="0" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleStartSchedule}
                loading={loading}
                size="large"
              >
                开始排产
              </Button>
              {loading && (
                <Button
                  danger
                  icon={<StopOutlined />}
                  onClick={handleCancel}
                  size="large"
                >
                  取消
                </Button>
              )}
              <Button
                icon={<PlusOutlined />}
                onClick={handleOpenInsert}
                size="large"
              >
                紧急插单
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </div>

      {/* 排产中进度 - Glass Card */}
      {scheduleStatus === 'RUNNING' && (
        <div className="glass-card animate-fade-in" style={{ padding: 24, marginBottom: 16 }}>
          <Spin spinning tip="排产计算中...">
            <div style={{ padding: 20 }}>
              <Progress percent={progress} status="active" />
              <p style={{ textAlign: 'center', marginTop: 8, color: '#475569' }}>
                正在求解最优排产方案，请稍候...
              </p>
            </div>
          </Spin>
        </div>
      )}

      {/* 工艺流程图 - Glass Card */}
      <div className="glass-card animate-slide-up" style={{ padding: 24, marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#1E3A8A', marginBottom: 16, letterSpacing: '-0.01em' }}>
          工艺流程图
        </div>
        <ProcessFlow height={625} />
      </div>

      {/* 结果摘要 - Glass Card */}
      {resultSummary && scheduleStatus === 'SUCCESS' && (
        <div className="glass-card animate-fade-in" style={{ padding: 24, marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1E3A8A', marginBottom: 16, letterSpacing: '-0.01em' }}>
            排产结果摘要
          </div>
          <Descriptions bordered column={3} size="small">
            <Descriptions.Item label="计划ID">
              <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13 }}>{resultSummary.plan_id}</span>
            </Descriptions.Item>
            <Descriptions.Item label="求解状态">
              <Tag color={resultSummary.solve_status === 'OPTIMAL' ? 'green' : resultSummary.solve_status === 'FEASIBLE' ? 'blue' : 'red'}>
                {resultSummary.solve_status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="任务数量">
              <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13, fontWeight: 600 }}>{resultSummary.task_count}</span>
            </Descriptions.Item>
            <Descriptions.Item label="求解耗时">
              <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13 }}>{resultSummary.solve_time_seconds}s</span>
            </Descriptions.Item>
            <Descriptions.Item label="求解器">
              {resultSummary.solver_name}
            </Descriptions.Item>
          </Descriptions>
        </div>
      )}

      {/* 结果展示 - Glass Card with Tabs */}
      {result && scheduleStatus === 'SUCCESS' && (
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <div className="glass-card animate-slide-up" style={{ padding: 24 }}>
              <Tabs
                defaultActiveKey="gantt"
                items={[
                  {
                    key: 'gantt',
                    label: '排产甘特图',
                    children: <GanttChart data={result} height={450} />,
                  },
                  {
                    key: 'matrix',
                    label: '计划矩阵',
                    children: <PlanMatrix data={result} onCellChange={handleCellChange} />,
                  },
                  {
                    key: 'load',
                    label: '负荷率分析',
                    children: <LoadChart loadRates={result.loadRates} />,
                  },
                  {
                    key: 'rules',
                    label: '规则评分',
                    children: result.ruleReport ? (
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 12 }}>
                          硬规则遵守性
                          {result.ruleReport.hard_violations === 0 ? (
                            <Tag color="green" style={{ marginLeft: 8 }}>全部通过</Tag>
                          ) : (
                            <Tag color="red" style={{ marginLeft: 8 }}>{result.ruleReport.hard_violations} 项违反</Tag>
                          )}
                        </div>
                        <Descriptions bordered column={1} size="small" style={{ marginBottom: 24 }}>
                          {result.ruleReport.hard_rules.map((rule) => (
                            <Descriptions.Item key={rule.code} label={rule.name}>
                              <Tag color={rule.status === 'PASS' ? 'green' : 'red'} style={{ marginRight: 8 }}>
                                {rule.status}
                              </Tag>
                              <span style={{ fontSize: 12, color: '#666' }}>{rule.detail}</span>
                            </Descriptions.Item>
                          ))}
                        </Descriptions>

                        <div style={{ fontSize: 14, fontWeight: 600, color: '#1E3A8A', marginBottom: 12 }}>
                          软规则评分
                        </div>
                        <Descriptions bordered column={1} size="small">
                          {Object.entries(result.ruleReport.soft_scores).map(([code, score]) => (
                            <Descriptions.Item key={code} label={`${score.name} (权重 ${score.weight})`}>
                              <span style={{ fontFamily: "'Fira Code', monospace", fontWeight: 600, color: score.score >= 0.8 ? '#52c41a' : score.score >= 0.5 ? '#faad14' : '#ff4d4f' }}>
                                {(score.score * 100).toFixed(1)}%
                              </span>
                              <span style={{ fontSize: 12, color: '#666', marginLeft: 12 }}>{score.detail}</span>
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      </div>
                    ) : (
                      <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                        该求解器未提供规则评分信息
                      </div>
                    ),
                  },
                ]}
              />
            </div>
          </Col>

          {/* 操作按钮 */}
          <Col span={24}>
            <Space>
              <Button type="primary" onClick={handlePushToHap} loading={pushing} icon={<CloudUploadOutlined />}>
                推送至 HAP
              </Button>
              <Button onClick={handleExport} icon={<DownloadOutlined />}>
                导出 CSV
              </Button>
            </Space>
          </Col>
        </Row>
      )}

      {/* 紧急插单弹窗 - Glass Modal */}
      <Modal
        title="紧急插单"
        open={insertModalVisible}
        onOk={handleSubmitInsert}
        onCancel={() => setInsertModalVisible(false)}
        confirmLoading={insertLoading}
        okText="提交"
        cancelText="取消"
      >
        <Form
          form={insertForm}
          layout="vertical"
          initialValues={{ dueDate: dayjs().add(2, 'day') }}
        >
          <Form.Item name="productId" label="产品" rules={[{ required: true, message: '请选择产品' }]}>
            <Select
              placeholder="请选择产品"
              showSearch
              optionFilterProp="label"
              options={productOptions}
            />
          </Form.Item>
          <Form.Item name="quantity" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
            <InputNumber min={1} style={{ width: '100%' }} placeholder="请输入需求数量" />
          </Form.Item>
          <Form.Item name="dueDate" label="交期" rules={[{ required: true, message: '请选择交期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Schedule;
