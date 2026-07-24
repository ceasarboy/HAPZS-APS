import { Card, Spin, InputNumber, message } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changeoverMatrixApi, lineProcessConfigApi } from '../../api/entities';
import type { ChangeoverMatrix, LineProcessConfig } from '../../types/entities';

/** 换线矩阵管理页面 — 基于产线工艺配置的矩阵视图 */
const Changeover: React.FC = () => {
  const queryClient = useQueryClient();

  // 获取换线矩阵数据
  const { data: cmData, isLoading: cmLoading } = useQuery({
    queryKey: ['changeover-matrices', 'all'],
    queryFn: async () => {
      const res = await changeoverMatrixApi.getList({ limit: 1000 });
      return res.items;
    },
  });

  // 获取产线工艺配置数据
  const { data: lpcData, isLoading: lpcLoading } = useQuery({
    queryKey: ['line-process-configs', 'all'],
    queryFn: async () => {
      const res = await lineProcessConfigApi.getList({ limit: 1000 });
      return res.items;
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, setup_time }: { id: string; setup_time: number }) => {
      return changeoverMatrixApi.update(id, { setup_time });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeover-matrices', 'all'] });
    },
    onError: () => {
      message.error('更新失败');
    },
  });

  if (cmLoading || lpcLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载换线矩阵..." />
      </div>
    );
  }

  const lpcs: LineProcessConfig[] = (lpcData ?? []).sort((a, b) =>
    (a.lpc_code || '').localeCompare(b.lpc_code || '')
  );
  const cms: ChangeoverMatrix[] = cmData ?? [];

  // 构建查找映射: from_lpc_id → to_lpc_id → ChangeoverMatrix
  const cmMap = new Map<string, Map<string, ChangeoverMatrix>>();
  cms.forEach((cm) => {
    if (!cm.from_lpc_id) return;
    if (!cmMap.has(cm.from_lpc_id)) {
      cmMap.set(cm.from_lpc_id, new Map());
    }
    if (cm.to_lpc_id) {
      cmMap.get(cm.from_lpc_id)!.set(cm.to_lpc_id, cm);
    }
  });

  /** 处理单元格编辑 */
  const handleCellChange = (cm: ChangeoverMatrix | undefined, value: number | null) => {
    if (!cm || value === null) return;
    updateMutation.mutate({ id: cm.id, setup_time: value });
  };

  return (
    <Card
      title="换线矩阵"
      extra={
        <span style={{ color: '#999', fontSize: 12 }}>
          行=当前产线工艺，列=下一产线工艺，交叉点=换线时间(分钟)
        </span>
      }
    >
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{
                position: 'sticky', left: 0, zIndex: 2,
                background: '#fafafa', border: '1px solid #d9d9d9',
                padding: '4px 8px', minWidth: 120, textAlign: 'center',
              }}>
                当前 \ 下一
              </th>
              {lpcs.map((lpc) => (
                <th key={lpc.id} style={{
                  border: '1px solid #d9d9d9', padding: '4px 6px',
                  minWidth: 70, textAlign: 'center', background: '#fafafa',
                  whiteSpace: 'nowrap',
                }}>
                  {lpc.lpc_code}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lpcs.map((fromLpc) => (
              <tr key={fromLpc.id}>
                <td style={{
                  position: 'sticky', left: 0, zIndex: 1,
                  background: '#fafafa', border: '1px solid #d9d9d9',
                  padding: '4px 8px', fontWeight: 500, whiteSpace: 'nowrap',
                }}>
                  {fromLpc.lpc_code}
                </td>
                {lpcs.map((toLpc) => {
                  const cm = cmMap.get(fromLpc.id)?.get(toLpc.id);
                  const isSelf = fromLpc.id === toLpc.id;
                  return (
                    <td key={toLpc.id} style={{
                      border: '1px solid #d9d9d9', padding: '2px',
                      textAlign: 'center',
                      background: isSelf ? '#f5f5f5' : undefined,
                    }}>
                      {isSelf ? (
                        <span style={{ color: '#ccc' }}>—</span>
                      ) : cm ? (
                        <InputNumber
                          size="small"
                          style={{ width: 60 }}
                          value={cm.setup_time ?? 0}
                          min={0}
                          onChange={(val) => handleCellChange(cm, val)}
                        />
                      ) : (
                        <span style={{ color: '#ccc' }}>-</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 图例 */}
      <div style={{ marginTop: 12, color: '#999', fontSize: 12 }}>
        <span style={{ display: 'inline-block', width: 16, height: 16, background: '#f5f5f5', border: '1px solid #d9d9d9', marginRight: 4, verticalAlign: 'middle' }} />
        = 自身（无需换线）　
        可直接编辑交叉点的换线时间，修改后自动保存
      </div>
    </Card>
  );
};

export default Changeover;
