import { Card, Button, message, Spin } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ChangeoverTable from '../../components/ChangeoverTable';
import type { ChangeoverCell } from '../../components/ChangeoverTable';
import { getChangeover, updateChangeover, syncChangeover } from '../../api/changeover';

/** 换线矩阵管理页面 */
const Changeover: React.FC = () => {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['changeover'],
    queryFn: async () => {
      const res = await getChangeover();
      return res.data;
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncChangeover,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeover'] });
      message.success('同步完成');
    },
    onError: () => {
      message.error('同步失败');
    },
  });

  const updateMutation = useMutation({
    mutationFn: updateChangeover,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeover'] });
      message.success('换线矩阵已更新');
    },
    onError: () => {
      message.error('更新失败');
    },
  });

  /** 从 HAP 同步换线数据 */
  const handleSync = () => {
    syncMutation.mutate();
  };

  /** 处理数据变更 */
  const handleChange = (newData: ChangeoverCell[]) => {
    updateMutation.mutate(newData);
  };

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" spinning tip="加载换线矩阵...">
          <div style={{ minHeight: 200 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div>
      <Card
        title="换线矩阵管理"
        extra={
          <Button
            icon={<SyncOutlined />}
            onClick={handleSync}
            loading={syncMutation.isPending}
          >
            从 HAP 同步
          </Button>
        }
      >
        <ChangeoverTable data={data ?? []} onChange={handleChange} />
      </Card>
    </div>
  );
};

export default Changeover;
