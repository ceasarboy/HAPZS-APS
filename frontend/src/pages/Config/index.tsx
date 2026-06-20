import { useState, useEffect } from 'react';
import { Form, Slider, Button, Select, message, Divider, Spin, Input } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getConfig, updateConfig, getHapConfig, updateHapConfig } from '../../api/config';
import type { SystemConfig, HapConfig } from '../../api/config';
import type { HardRule, SoftRule } from '../../types/schedule';

/** 硬规则选项 */
const hardRuleOptions: { label: string; value: HardRule }[] = [
  { label: '有限产能', value: 'FINITE_CAPACITY' },
  { label: '工序顺序', value: 'PROCESS_ORDER' },
  { label: '资源兼容性', value: 'RESOURCE_COMPATIBILITY' },
];

/** 软规则选项 */
const softRuleOptions: { label: string; value: SoftRule }[] = [
  { label: '准时交付优先', value: 'OTD_PRIORITY' },
  { label: '换线最小化', value: 'SETUP_MINIMIZATION' },
  { label: '负荷均衡', value: 'LOAD_BALANCING' },
];

/** 系统配置页面 */
const Config: React.FC = () => {
  const [form] = Form.useForm();
  const [hapForm] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [hapSaving, setHapSaving] = useState(false);
  const queryClient = useQueryClient();

  const { data: config, isLoading } = useQuery({
    queryKey: ['config'],
    queryFn: async () => {
      const res = await getConfig();
      return res.data;
    },
  });

  const { data: hapConfig } = useQuery({
    queryKey: ['hapConfig'],
    queryFn: async () => {
      const res = await getHapConfig();
      return res.data;
    },
  });

  const updateMutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      message.success('配置已保存');
      setSaving(false);
    },
    onError: () => {
      message.error('保存配置失败');
      setSaving(false);
    },
  });

  const hapUpdateMutation = useMutation({
    mutationFn: updateHapConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hapConfig'] });
      message.success('HAP 配置已保存');
      setHapSaving(false);
    },
    onError: () => {
      message.error('保存 HAP 配置失败');
      setHapSaving(false);
    },
  });

  /** 配置加载后设置表单值 */
  useEffect(() => {
    if (config) {
      const cfg = config as unknown as Record<string, unknown>;
      form.setFieldsValue({
        solver_type: cfg.solver_type ?? 'ortools',
        hard_rules: (cfg.hard_rules as string[]) ?? ['FINITE_CAPACITY', 'PROCESS_ORDER', 'RESOURCE_COMPATIBILITY'],
        soft_rules: (cfg.soft_rules as string[]) ?? ['OTD_PRIORITY', 'SETUP_MINIMIZATION', 'LOAD_BALANCING'],
        soft_rule_weights: (cfg.soft_rule_weights ?? {
          OTD_PRIORITY: 0.35, SETUP_MINIMIZATION: 0.25, LOAD_BALANCING: 0.15,
        }) as Record<string, number>,
      });
    }
  }, [config, form]);

  /** HAP 配置加载后设置表单值 */
  useEffect(() => {
    if (hapConfig) {
      hapForm.setFieldsValue({
        hap_app_id: hapConfig.hap_app_id ?? '',
        hap_app_key: hapConfig.hap_app_key ?? '',
        hap_sign: hapConfig.hap_sign ?? '',
        hap_base_url: hapConfig.hap_base_url ?? 'https://api.mingdao.com',
      });
    }
  }, [hapConfig, hapForm]);

  /** 保存求解器配置 */
  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const data: SystemConfig = {
        solver_type: values.solver_type,
        start_time: config?.start_time ?? '',
        end_time: config?.end_time ?? '',
        config: {
          hard_rules: values.hard_rules,
          soft_rules: values.soft_rules,
          soft_rule_weights: values.soft_rule_weights,
        },
      };
      updateMutation.mutate(data);
    } catch {
      // 表单校验失败
    }
  };

  /** 保存 HAP 配置 */
  const handleHapSave = async () => {
    try {
      const values = await hapForm.validateFields();
      setHapSaving(true);
      const data: HapConfig = {
        hap_app_id: values.hap_app_id ?? '',
        hap_app_key: values.hap_app_key ?? '',
        hap_sign: values.hap_sign ?? '',
        hap_base_url: values.hap_base_url ?? 'https://api.mingdao.com',
      };
      hapUpdateMutation.mutate(data);
    } catch {
      // 表单校验失败
    }
  };

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" spinning tip="加载配置...">
          <div style={{ minHeight: 200 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div>
      <div className="glass-card animate-slide-up" style={{ padding: 24, marginBottom: 24 }}>
        <h3 style={{ marginBottom: 16 }}>系统配置</h3>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            solver_type: 'ortools',
            hard_rules: ['FINITE_CAPACITY', 'PROCESS_ORDER', 'RESOURCE_COMPATIBILITY'],
            soft_rules: ['OTD_PRIORITY', 'SETUP_MINIMIZATION', 'LOAD_BALANCING'],
            soft_rule_weights: { OTD_PRIORITY: 0.35, SETUP_MINIMIZATION: 0.25, LOAD_BALANCING: 0.15 },
          }}
          style={{ maxWidth: 800 }}
        >
          {/* 求解器选择 */}
          <Divider orientation="left">求解器</Divider>
          <Form.Item name="solver_type" label="求解器类型">
            <Select style={{ width: 200 }}>
              <Select.Option value="ortools">OR-Tools (CP-SAT)</Select.Option>
              <Select.Option value="ga">遗传算法 (GA)</Select.Option>
            </Select>
          </Form.Item>

          {/* 硬规则开关 */}
          <Divider orientation="left">硬规则</Divider>
          <Form.Item name="hard_rules" label="启用的硬规则">
            <Select mode="multiple" options={hardRuleOptions} />
          </Form.Item>

          {/* 软规则开关 */}
          <Divider orientation="left">软规则</Divider>
          <Form.Item name="soft_rules" label="启用的软规则">
            <Select mode="multiple" options={softRuleOptions} />
          </Form.Item>

          {/* 软规则权重 */}
          <Divider orientation="left">软规则权重</Divider>
          <Form.Item name={['soft_rule_weights', 'OTD_PRIORITY']} label="准时交付权重">
            <Slider min={0} max={1} step={0.05} marks={{ 0: '0', 0.5: '0.5', 1: '1' }} />
          </Form.Item>
          <Form.Item name={['soft_rule_weights', 'SETUP_MINIMIZATION']} label="换线最小化权重">
            <Slider min={0} max={1} step={0.05} marks={{ 0: '0', 0.5: '0.5', 1: '1' }} />
          </Form.Item>
          <Form.Item name={['soft_rule_weights', 'LOAD_BALANCING']} label="负荷均衡权重">
            <Slider min={0} max={1} step={0.05} marks={{ 0: '0', 0.5: '0.5', 1: '1' }} />
          </Form.Item>

          {/* 保存按钮 */}
          <Form.Item>
            <Button type="primary" onClick={handleSave} loading={saving} size="large">
              保存配置
            </Button>
          </Form.Item>
        </Form>
      </div>

      {/* 明道云 HAP 连接配置 */}
      <div className="glass-card animate-slide-up" style={{ padding: 24 }}>
        <h3 style={{ marginBottom: 16 }}>明道云 HAP 连接配置</h3>
        <Form
          form={hapForm}
          layout="vertical"
          initialValues={{
            hap_app_id: '',
            hap_app_key: '',
            hap_sign: '',
            hap_base_url: 'https://api.mingdao.com',
          }}
          style={{ maxWidth: 800 }}
        >
          <Form.Item name="hap_app_id" label="App ID" rules={[{ required: true, message: '请输入 App ID' }]}>
            <Input placeholder="请输入明道云应用 App ID" />
          </Form.Item>
          <Form.Item name="hap_app_key" label="App Key" rules={[{ required: true, message: '请输入 App Key' }]}>
            <Input placeholder="请输入明道云应用 App Key" />
          </Form.Item>
          <Form.Item name="hap_sign" label="Sign" rules={[{ required: true, message: '请输入 Sign' }]}>
            <Input.Password placeholder="请输入明道云应用 Sign" />
          </Form.Item>
          <Form.Item name="hap_base_url" label="Base URL">
            <Input placeholder="https://api.mingdao.com" />
          </Form.Item>

          {/* 保存按钮 */}
          <Form.Item>
            <Button type="primary" onClick={handleHapSave} loading={hapSaving} size="large">
              保存 HAP 配置
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
};

export default Config;
