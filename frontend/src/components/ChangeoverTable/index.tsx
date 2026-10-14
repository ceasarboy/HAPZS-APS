import { Table, InputNumber, Space } from 'antd';
import type { ColumnsType } from 'antd/es/table';

/** 换线矩阵单元格 */
export interface ChangeoverCell {
  /** 当前产品 */
  fromProduct: string;
  /** 下一产品 */
  toProduct: string;
  /** 换线时间（分钟） */
  changeoverTime: number;
}

/** 换线矩阵编辑组件属性 */
interface ChangeoverTableProps {
  /** 换线矩阵数据 */
  data: ChangeoverCell[];
  /** 数据变更回调 */
  onChange?: (data: ChangeoverCell[]) => void;
}

/** 换线矩阵编辑组件：以表格形式展示和编辑产品间换线时间 */
const ChangeoverTable: React.FC<ChangeoverTableProps> = ({ data, onChange }) => {
  // 收集所有产品（去重）
  const products = Array.from(
    new Set([
      ...data.map((d) => d.fromProduct),
      ...data.map((d) => d.toProduct),
    ])
  );

  // 构建查找映射：fromProduct -> toProduct -> changeoverTime
  const lookup = new Map<string, Map<string, number>>();
  data.forEach((d) => {
    if (!lookup.has(d.fromProduct)) {
      lookup.set(d.fromProduct, new Map());
    }
    lookup.get(d.fromProduct)!.set(d.toProduct, d.changeoverTime);
  });

  /** 处理换线时间变更 */
  const handleChange = (fromProduct: string, toProduct: string, value: number | null) => {
    if (!onChange || value === null) return;
    const newData = data.map((d) => {
      if (d.fromProduct === fromProduct && d.toProduct === toProduct) {
        return { ...d, changeoverTime: value };
      }
      return d;
    });
    // 如果不存在则新增
    if (!lookup.get(fromProduct)?.has(toProduct)) {
      newData.push({ fromProduct, toProduct, changeoverTime: value });
    }
    onChange(newData);
  };

  // 构建列定义：第一列为当前产品，后续列为目标产品
  const columns: ColumnsType<Record<string, unknown>> = [
    {
      title: '当前 \\ 下一',
      dataIndex: 'fromProduct',
      key: 'fromProduct',
      fixed: 'left',
      width: 120,
      render: (text: string) => <strong>{text}</strong>,
    },
    ...products.map((product) => ({
      title: product,
      dataIndex: `to_${product}`,
      key: `to_${product}`,
      width: 100,
      render: (_: unknown, record: Record<string, unknown>) => {
        const from = record.fromProduct as string;
        const time = lookup.get(from)?.get(product);
        // 对角线（自身换线）显示 "-"
        if (from === product) return <span style={{ color: '#ccc' }}>-</span>;
        return (
          <Space.Compact style={{ width: '100%' }}>
            <InputNumber
              size="small"
              min={0}
              value={time ?? 0}
              onChange={(val) => handleChange(from, product, val)}
              style={{ width: '100%' }}
            />
            <span style={{ lineHeight: '24px', padding: '0 4px', background: '#fafafa', border: '1px solid #d9d9d9', borderLeft: 'none', fontSize: 12 }}>分</span>
          </Space.Compact>
        );
      },
    })),
  ];

  // 构建数据源
  const dataSource = products.map((from) => {
    const row: Record<string, unknown> = { fromProduct: from, key: from };
    products.forEach((to) => {
      row[`to_${to}`] = lookup.get(from)?.get(to) ?? 0;
    });
    return row;
  });

  return (
    <Table
      columns={columns}
      dataSource={dataSource}
      pagination={false}
      scroll={{ x: 'max-content' }}
      size="small"
      bordered
    />
  );
};

export default ChangeoverTable;
