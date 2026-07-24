/** 数据管理页面 - 根据 URL 参数动态加载对应表的 CRUD 界面 */

import { useParams } from 'react-router-dom';
import CrudPage from '../../components/CrudPage';
import { tableRegistry, type TableKey } from '../../config/tables';

export default function DataManager() {
  const { tableKey } = useParams<{ tableKey: string }>();
  const config = tableKey ? tableRegistry[tableKey as TableKey] : undefined;

  if (!config) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#94A3B8' }}>
        <h2>请从左侧菜单选择数据表</h2>
      </div>
    );
  }

  return <CrudPage config={config} />;
}
