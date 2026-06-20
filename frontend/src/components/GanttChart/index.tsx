import { useMemo, useState } from 'react';
import { Select, Radio, Space } from 'antd';
import ReactECharts from 'echarts-for-react';
import type { ScheduleResult, PlanCell } from '../../types/result';

/** 甘特图组件属性 */
interface GanttChartProps {
  data: ScheduleResult;
  height?: number;
}

/** seq → 颜色映射（渐变：蓝→绿→橙→红，最后工序深色） */
const SEQ_COLORS: Record<number, string> = {
  1: '#4096ff',  // 浅蓝
  2: '#36cfc9',  // 青色
  3: '#ffa940',  // 橙色（并行组）
  4: '#9254de',  // 紫色
  5: '#ff7a45',  // 深橙
  6: '#f5222d',  // 红色
  7: '#fa541c',  // 深红
  8: '#820014',  // 暗红
  9: '#5b0014',  // 最后工序
};

/** 工序编码 → 中文名 */
const PROCESS_NAME_MAP: Record<string, string> = {
  'PROC-SMT-01': 'SMT贴片',
  'PROC-REF-01': '回流焊',
  'PROC-AOI-01': 'AOI检测',
  'PROC-ICT-01': '在线测试',
  'PROC-FCT-01': '功能测试',
  'PROC-COA-01': '涂覆',
  'PROC-XRAY-01': 'X-Ray检测',
  'PROC-ASM-01': '组装',
  'PROC-BUR-01': '老化测试',
  'PROC-PKG-01': '包装',
};

/** 工序编码 → 缩写 */
const PROCESS_SHORT: Record<string, string> = {
  'PROC-SMT-01': 'SMT',
  'PROC-REF-01': '回流',
  'PROC-AOI-01': 'AOI',
  'PROC-ICT-01': 'ICT',
  'PROC-FCT-01': 'FCT',
  'PROC-COA-01': '涂覆',
  'PROC-XRAY-01': 'X-Ray',
  'PROC-ASM-01': '组装',
  'PROC-BUR-01': '老化',
  'PROC-PKG-01': '包装',
};

/** 获取工序中文名 */
function getProcessName(code: string): string {
  return PROCESS_NAME_MAP[code] || code;
}

/** 获取工序缩写 */
function getProcessShort(code: string): string {
  return PROCESS_SHORT[code] || code;
}

/** 将 timeSlot 字符串转为 Date
 *  支持格式: "2026-06-15 11:00-12:00" 或 "2026-06-15 11:00"
 */
function parseTimeSlot(ts: string): Date {
  const match = ts.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  if (match) {
    return new Date(`${match[1]}T${match[2]}:00`);
  }
  return new Date(ts.replace(' ', 'T'));
}

/** 依赖类型 → 连线样式 */
const DEP_LINE_STYLE: Record<string, { type: string; color: string; label: string }> = {
  'FS': { type: 'solid', color: '#595959', label: 'FS 完成→开始' },
  'SS': { type: 'dashed', color: '#1890ff', label: 'SS 开始→开始' },
  'FF': { type: 'dotted', color: '#52c41a', label: 'FF 完成→完成' },
  'SF': { type: 'dashed', color: '#fa8c16', label: 'SF 开始→完成' },
};

/** 甘特图组件：支持按产线/按产品两种视图，支持产品筛选 */
const GanttChart: React.FC<GanttChartProps> = ({ data, height = 500 }) => {
  const [viewMode, setViewMode] = useState<'line' | 'product'>('product');
  const [selectedProduct, setSelectedProduct] = useState<string | undefined>(undefined);

  // 收集所有产品
  const products = useMemo(() => {
    const map = new Map<string, string>();
    (data?.workcenterPlans ?? []).forEach((wp) => {
      (wp.cells ?? []).forEach((c) => {
        if (!map.has(c.productCode)) {
          map.set(c.productCode, c.productName);
        }
      });
    });
    return Array.from(map.entries()).map(([code, name]) => ({ code, name }));
  }, [data]);

  // 计算每个产品的最大 seq（用于标记最后工序）
  const maxSeqByProduct = useMemo(() => {
    const map = new Map<string, number>();
    (data?.workcenterPlans ?? []).forEach((wp) => {
      (wp.cells ?? []).forEach((c) => {
        const seq = c.seq ?? 0;
        const prev = map.get(c.productCode) ?? 0;
        if (seq > prev) map.set(c.productCode, seq);
      });
    });
    return map;
  }, [data]);

  const option = useMemo(() => {
    const workcenterPlans = data?.workcenterPlans ?? [];
    if (workcenterPlans.length === 0) return null;

    // 收集所有 cell
    interface CellItem {
      workcenterCode: string;
      workcenterName: string;
      startTime: Date;
      endTime: Date;
      cell: PlanCell;
    }

    const allCells: CellItem[] = [];
    let minTime = Infinity;
    let maxTime = -Infinity;

    workcenterPlans.forEach((wp) => {
      (wp.cells ?? []).forEach((cell) => {
        const start = parseTimeSlot(cell.timeSlot);
        const end = new Date(start.getTime() + 60 * 60 * 1000);
        if (start.getTime() < minTime) minTime = start.getTime();
        if (end.getTime() > maxTime) maxTime = end.getTime();
        allCells.push({
          workcenterCode: wp.workcenterCode,
          workcenterName: wp.workcenterName,
          startTime: start,
          endTime: end,
          cell,
        });
      });
    });

    if (allCells.length === 0) return null;

    // 按产品筛选
    const filtered = selectedProduct
      ? allCells.filter((c) => c.cell.productCode === selectedProduct)
      : allCells;

    if (filtered.length === 0) return null;

    if (viewMode === 'product') {
      // === 按产品视图：Y 轴 = 工序（按 seq 排序），展示工艺路线 ===
      const processMap = new Map<string, { seq: number }>();
      filtered.forEach((c) => {
        const code = c.cell.processCode ?? '';
        if (code && !processMap.has(code)) {
          processMap.set(code, { seq: c.cell.seq ?? 0 });
        }
      });

      const processList = Array.from(processMap.entries())
        .sort((a, b) => a[1].seq !== b[1].seq ? a[1].seq - b[1].seq : a[0].localeCompare(b[0]));

      // Y 轴标签：工序中文名 + seq
      const yCategories = processList.map(([code, info]) => {
        const short = getProcessShort(code);
        const sameSeqCount = processList.filter(([, p]) => p.seq === info.seq).length;
        return sameSeqCount > 1 ? `${short} (seq=${info.seq} 并行)` : `${short} (seq=${info.seq})`;
      });

      // 合并连续时段
      interface MergedBar {
        yIndex: number;
        startTime: Date;
        endTime: Date;
        productCode: string;
        productName: string;
        processCode: string;
        seq: number;
        quantity: number;
        workcenterName: string;
        frozen: boolean;
        isLast: boolean;
        priority: string;
        dependencyType: string;
        waitTime: number;
        prepTime: number;
      }

      const sorted = [...filtered].sort((a, b) => {
        const seqA = a.cell.seq ?? 0;
        const seqB = b.cell.seq ?? 0;
        if (seqA !== seqB) return seqA - seqB;
        const procA = a.cell.processCode ?? '';
        const procB = b.cell.processCode ?? '';
        if (procA !== procB) return procA.localeCompare(procB);
        return a.startTime.getTime() - b.startTime.getTime();
      });

      const mergedBars: MergedBar[] = [];
      for (const item of sorted) {
        const processIdx = processList.findIndex(([code]) => code === (item.cell.processCode ?? ''));
        if (processIdx < 0) continue;
        const seq = item.cell.seq ?? 0;
        const isLast = seq === (maxSeqByProduct.get(item.cell.productCode) ?? 0);
        const last = mergedBars[mergedBars.length - 1];
        if (
          last &&
          last.yIndex === processIdx &&
          last.processCode === (item.cell.processCode ?? '') &&
          last.productCode === (item.cell.productCode ?? '') &&
          last.endTime.getTime() === item.startTime.getTime()
        ) {
          last.endTime = item.endTime;
          last.quantity += item.cell.quantity;
        } else {
          mergedBars.push({
            yIndex: processIdx,
            startTime: item.startTime,
            endTime: item.endTime,
            productCode: item.cell.productCode,
            productName: item.cell.productName,
            processCode: item.cell.processCode ?? '',
            seq,
            quantity: item.cell.quantity,
            workcenterName: item.workcenterName,
            frozen: item.cell.frozen,
            isLast,
            priority: item.cell.priority ?? '中',
            dependencyType: item.cell.dependencyType ?? 'FS',
            waitTime: item.cell.waitTime ?? 0,
            prepTime: item.cell.prepTime ?? 0,
          });
        }
      }

      const seriesData = mergedBars.map((bar) => {
        const color = SEQ_COLORS[bar.seq] || '#8c8c8c';
        return {
          value: [
            yCategories[bar.yIndex],
            bar.startTime.getTime(),
            bar.endTime.getTime(),
            bar.quantity,
            bar.productName,
            bar.processCode,
            bar.seq,
            bar.workcenterName,
            bar.isLast ? 1 : 0,
            bar.priority,
            bar.dependencyType,
            bar.waitTime,
            bar.prepTime,
          ],
          itemStyle: {
            color: bar.frozen ? '#d9d9d9' : color,
            opacity: bar.frozen ? 0.5 : 0.85,
            borderColor: bar.isLast ? '#000' : 'transparent',
            borderWidth: bar.isLast ? 2 : 0,
          },
        };
      });

      return {
        tooltip: {
          formatter: (params: any) => {
            const val = params.value;
            const start = new Date(val[1]);
            const end = new Date(val[2]);
            const qty = val[3];
            const prodName = val[4];
            const procCode = val[5];
            const seq = val[6];
            const wcName = val[7];
            const isLast = val[8] === 1;
            const priority = val[9] || '中';
            const depType = val[10] || 'FS';
            const waitTime = val[11] || 0;
            const prepTime = val[12] || 0;
            const procName = getProcessName(procCode);
            const startStr = `${start.getMonth() + 1}/${start.getDate()} ${String(start.getHours()).padStart(2, '0')}:00`;
            const endStr = `${end.getMonth() + 1}/${end.getDate()} ${String(end.getHours()).padStart(2, '0')}:00`;
            const lastTag = isLast ? ' <span style="color:#f5222d;font-weight:bold">[最后工序]</span>' : '';
            const parallelTag = (seq === 3) ? ' <span style="color:#fa8c16">[并行]</span>' : '';
            const priorityColors: Record<string, string> = { '紧急': '#f5222d', '高': '#fa8c16', '中': '#8c8c8c', '低': '#bfbfbf' };
            const priColor = priorityColors[priority] || '#8c8c8c';
            const priorityTag = ` <span style="color:${priColor};font-weight:bold">[${priority}]</span>`;
            const depStyle = DEP_LINE_STYLE[depType] || DEP_LINE_STYLE['FS'];
            const depTag = ` <span style="color:${depStyle.color};font-weight:bold">[${depType}]</span>`;
            const delayInfo = (waitTime > 0 || prepTime > 0) ? `<br/><span style="color:#fa8c16;font-weight:bold">⏳等待: ${waitTime}min${waitTime >= 60 ? ` (${Math.round(waitTime/60)}h)` : ''}</span>${prepTime > 0 ? ` / 准备: ${prepTime}min` : ''}` : '';
            return `<b>${prodName}</b> - ${procName}${lastTag}${parallelTag}${priorityTag}${depTag}<br/>`
              + `工序顺序: seq=${seq}<br/>`
              + `产线: ${wcName}<br/>`
              + `时间: ${startStr} ~ ${endStr}<br/>`
              + `数量: ${qty}${delayInfo}`;
          },
        },
        dataZoom: [
          { type: 'slider' as const, xAxisIndex: 0, filterMode: 'weakFilter' as const, bottom: 10, height: 20 },
          { type: 'inside' as const, xAxisIndex: 0, filterMode: 'weakFilter' as const },
        ],
        grid: { left: 140, right: 30, top: 20, bottom: 60 },
        xAxis: {
          type: 'time' as const,
          min: minTime,
          max: maxTime,
          axisLabel: {
            formatter: (val: number) => {
              const d = new Date(val);
              return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
            },
            rotate: 30,
            fontSize: 11,
          },
          splitLine: { show: true, lineStyle: { type: 'dashed' as const, color: '#f0f0f0' } },
        },
        yAxis: {
          type: 'category' as const,
          data: yCategories,
          inverse: true,
          axisLabel: { fontSize: 11, fontWeight: 500 },
        },
        series: [{
          type: 'custom' as const,
          dimensions: ['yCategory', 'start', 'end', 'quantity', 'productName', 'processCode', 'seq', 'workcenterName', 'isLast'],
          encode: { x: [1, 2], y: 0 },
          renderItem: (_params: any, api: any) => {
            const yIdx = api.value(0);
            const start = api.coord([api.value(1), yIdx]);
            const end = api.coord([api.value(2), yIdx]);
            const barHeight = api.size([0, 1])[1] * 0.6;
            const rectShape = { x: start[0], y: start[1] - barHeight / 2, width: end[0] - start[0], height: barHeight };
            const procCode = api.value(5) as string;
            const wcName = api.value(7) as string;
            const isLast = api.value(8) === 1;
            const shortProc = getProcessShort(procCode);
            const barWidth = rectShape.width;
            const label = barWidth > 80 ? `${shortProc} @${wcName}` : (barWidth > 40 ? shortProc : '');
            const dataIndex = _params.dataIndex;
            const dataItem = seriesData[dataIndex];
            const fillColor = dataItem?.itemStyle?.color ?? '#8c8c8c';
            const opacity = dataItem?.itemStyle?.opacity ?? 0.85;
            const borderColor = isLast ? '#000' : 'transparent';
            const borderWidth = isLast ? 2 : 0;
            const depType = (dataItem?.value?.[10] as string) || 'FS';

            const children: any[] = [
              // 条形主体
              {
                type: 'rect' as const,
                shape: rectShape,
                style: { fill: fillColor, opacity, stroke: borderColor, lineWidth: borderWidth },
              },
            ];

            // 条形内文字
            if (label) {
              children.push({
                type: 'text' as const,
                style: {
                  text: label,
                  x: rectShape.x + rectShape.width / 2,
                  y: rectShape.y + rectShape.height / 2,
                  textAlign: 'center' as const,
                  textVerticalAlign: 'middle' as const,
                  fill: '#fff',
                  fontSize: 10,
                  fontWeight: 500,
                },
              });
            }

            // 箭头：非最后工序在条形右侧加 "▶"
            if (!isLast && barWidth > 5) {
              children.push({
                type: 'text' as const,
                style: {
                  text: '▶',
                  x: rectShape.x + rectShape.width + 3,
                  y: rectShape.y + rectShape.height / 2,
                  textAlign: 'left' as const,
                  textVerticalAlign: 'middle' as const,
                  fill: '#999',
                  fontSize: 10,
                },
              });
            }

            // 最后工序标记：条形左侧加 "◆"
            if (isLast && barWidth > 5) {
              children.push({
                type: 'text' as const,
                style: {
                  text: '◆',
                  x: rectShape.x - 12,
                  y: rectShape.y + rectShape.height / 2,
                  textAlign: 'center' as const,
                  textVerticalAlign: 'middle' as const,
                  fill: '#f5222d',
                  fontSize: 10,
                },
              });
            }

            // 依赖类型标签：条形左上角
            if (depType && depType !== 'FS' && barWidth > 30) {
              const depStyle = DEP_LINE_STYLE[depType] || DEP_LINE_STYLE['FS'];
              children.push({
                type: 'text' as const,
                style: {
                  text: depType,
                  x: rectShape.x + 2,
                  y: rectShape.y - 2,
                  textAlign: 'left' as const,
                  textVerticalAlign: 'bottom' as const,
                  fill: depStyle.color,
                  fontSize: 9,
                  fontWeight: 600,
                },
              });
            }

            // 等待时间标注：条形右下角
            const waitTime = (dataItem?.value?.[11] as number) || 0;
            if (waitTime > 0 && barWidth > 20) {
              const waitHours = waitTime >= 60 ? `${Math.round(waitTime / 60)}h` : `${waitTime}min`;
              children.push({
                type: 'text' as const,
                style: {
                  text: `⏳${waitHours}`,
                  x: rectShape.x + rectShape.width - 2,
                  y: rectShape.y + rectShape.height + 2,
                  textAlign: 'right' as const,
                  textVerticalAlign: 'top' as const,
                  fill: '#fa8c16',
                  fontSize: 9,
                  fontWeight: 600,
                },
              });
            }

            return { type: 'group' as const, children };
          },
          data: seriesData,
        }],
      };
    } else {
      // === 按产线视图：Y 轴 = 产线 ===
      const workcenterNames = workcenterPlans.map((wp) => wp.workcenterName);

      const sorted = [...filtered].sort((a, b) => {
        const wcA = a.workcenterName;
        const wcB = b.workcenterName;
        if (wcA !== wcB) return wcA.localeCompare(wcB);
        const seqA = a.cell.seq ?? 0;
        const seqB = b.cell.seq ?? 0;
        if (seqA !== seqB) return seqA - seqB;
        return a.startTime.getTime() - b.startTime.getTime();
      });

      interface MergedBar {
        yIndex: number;
        startTime: Date;
        endTime: Date;
        productCode: string;
        productName: string;
        processCode: string;
        seq: number;
        quantity: number;
        frozen: boolean;
        isLast: boolean;
        priority: string;
      }

      const mergedBars: MergedBar[] = [];
      for (const item of sorted) {
        const yIdx = workcenterNames.indexOf(item.workcenterName);
        if (yIdx < 0) continue;
        const seq = item.cell.seq ?? 0;
        const isLast = seq === (maxSeqByProduct.get(item.cell.productCode) ?? 0);
        const last = mergedBars[mergedBars.length - 1];
        if (
          last &&
          last.yIndex === yIdx &&
          last.productCode === item.cell.productCode &&
          last.processCode === (item.cell.processCode ?? '') &&
          last.endTime.getTime() === item.startTime.getTime()
        ) {
          last.endTime = item.endTime;
          last.quantity += item.cell.quantity;
        } else {
          mergedBars.push({
            yIndex: yIdx,
            startTime: item.startTime,
            endTime: item.endTime,
            productCode: item.cell.productCode,
            productName: item.cell.productName,
            processCode: item.cell.processCode ?? '',
            seq,
            quantity: item.cell.quantity,
            frozen: item.cell.frozen,
            isLast,
            priority: item.cell.priority ?? '中',
          });
        }
      }

      const seriesData = mergedBars.map((bar) => {
        const color = SEQ_COLORS[bar.seq] || '#8c8c8c';
        return {
          value: [workcenterNames[bar.yIndex], bar.startTime.getTime(), bar.endTime.getTime(), bar.quantity, bar.productName, bar.processCode, bar.seq, bar.isLast ? 1 : 0, bar.priority],
          itemStyle: {
            color: bar.frozen ? '#d9d9d9' : color,
            opacity: bar.frozen ? 0.5 : 0.85,
            borderColor: bar.isLast ? '#000' : 'transparent',
            borderWidth: bar.isLast ? 2 : 0,
          },
        };
      });

      return {
        tooltip: {
          formatter: (params: any) => {
            const val = params.value;
            const wcName = val[0];
            const start = new Date(val[1]);
            const end = new Date(val[2]);
            const qty = val[3];
            const prodName = val[4];
            const procCode = val[5];
            const seq = val[6];
            const isLast = val[7] === 1;
            const priority = val[8] || '中';
            const procName = getProcessName(procCode);
            const startStr = `${start.getMonth() + 1}/${start.getDate()} ${String(start.getHours()).padStart(2, '0')}:00`;
            const endStr = `${end.getMonth() + 1}/${end.getDate()} ${String(end.getHours()).padStart(2, '0')}:00`;
            const lastTag = isLast ? ' <span style="color:#f5222d;font-weight:bold">[最后工序]</span>' : '';
            const priorityColors: Record<string, string> = { '紧急': '#f5222d', '高': '#fa8c16', '中': '#8c8c8c', '低': '#bfbfbf' };
            const priColor = priorityColors[priority] || '#8c8c8c';
            const priorityTag = ` <span style="color:${priColor};font-weight:bold">[${priority}]</span>`;
            return `${params.marker} <b>${prodName}</b> - ${procName}${lastTag}${priorityTag}<br/>产线: ${wcName}<br/>工序顺序: seq=${seq}<br/>时间: ${startStr} ~ ${endStr}<br/>数量: ${qty}`;
          },
        },
        dataZoom: [
          { type: 'slider' as const, xAxisIndex: 0, filterMode: 'weakFilter' as const, bottom: 10, height: 20 },
          { type: 'inside' as const, xAxisIndex: 0, filterMode: 'weakFilter' as const },
        ],
        grid: { left: 100, right: 30, top: 20, bottom: 60 },
        xAxis: {
          type: 'time' as const,
          min: minTime,
          max: maxTime,
          axisLabel: {
            formatter: (val: number) => {
              const d = new Date(val);
              return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
            },
            rotate: 30, fontSize: 11,
          },
          splitLine: { show: true, lineStyle: { type: 'dashed' as const, color: '#f0f0f0' } },
        },
        yAxis: {
          type: 'category' as const,
          data: workcenterNames,
          inverse: true,
          axisLabel: { fontSize: 12, fontWeight: 500 },
        },
        series: [{
          type: 'custom' as const,
          dimensions: ['yCategory', 'start', 'end', 'quantity', 'productName', 'processCode', 'seq', 'isLast'],
          encode: { x: [1, 2], y: 0 },
          renderItem: (_params: any, api: any) => {
            const yIdx = api.value(0);
            const start = api.coord([api.value(1), yIdx]);
            const end = api.coord([api.value(2), yIdx]);
            const barHeight = api.size([0, 1])[1] * 0.6;
            const rectShape = { x: start[0], y: start[1] - barHeight / 2, width: end[0] - start[0], height: barHeight };
            const prodName = api.value(4) as string;
            const procCode = api.value(5) as string;
            const isLast = api.value(7) === 1;
            const shortProc = getProcessShort(procCode);
            const barWidth = rectShape.width;
            const label = barWidth > 60 ? `${prodName.slice(0, 4)} ${shortProc}` : (barWidth > 30 ? shortProc : '');
            const dataIndex = _params.dataIndex;
            const dataItem = seriesData[dataIndex];
            const fillColor = dataItem?.itemStyle?.color ?? '#8c8c8c';
            const opacity = dataItem?.itemStyle?.opacity ?? 0.85;
            const borderColor = isLast ? '#000' : 'transparent';
            const borderWidth = isLast ? 2 : 0;

            const children: any[] = [
              {
                type: 'rect' as const,
                shape: rectShape,
                style: { fill: fillColor, opacity, stroke: borderColor, lineWidth: borderWidth },
              },
            ];

            if (label) {
              children.push({
                type: 'text' as const,
                style: {
                  text: label,
                  x: rectShape.x + rectShape.width / 2,
                  y: rectShape.y + rectShape.height / 2,
                  textAlign: 'center' as const,
                  textVerticalAlign: 'middle' as const,
                  fill: '#fff',
                  fontSize: 10,
                  fontWeight: 500,
                },
              });
            }

            // 最后工序标记
            if (isLast && barWidth > 5) {
              children.push({
                type: 'text' as const,
                style: {
                  text: '◆',
                  x: rectShape.x - 12,
                  y: rectShape.y + rectShape.height / 2,
                  textAlign: 'center' as const,
                  textVerticalAlign: 'middle' as const,
                  fill: '#f5222d',
                  fontSize: 10,
                },
              });
            }

            return { type: 'group' as const, children };
          },
          data: seriesData,
        }],
      };
    }
  }, [data, viewMode, selectedProduct, maxSeqByProduct]);

  return (
    <div>
      {/* 工具栏 */}
      <Space style={{ marginBottom: 12 }} wrap>
        <span style={{ fontSize: 13, color: '#666' }}>视图：</span>
        <Radio.Group
          value={viewMode}
          onChange={(e) => setViewMode(e.target.value)}
          size="small"
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="product">按产品工序</Radio.Button>
          <Radio.Button value="line">按产线</Radio.Button>
        </Radio.Group>
        <span style={{ fontSize: 13, color: '#666', marginLeft: 16 }}>产品：</span>
        <Select
          value={selectedProduct}
          onChange={setSelectedProduct}
          placeholder="全部产品"
          allowClear
          style={{ width: 200 }}
          size="small"
          options={products.map((p) => ({ label: p.name, value: p.code }))}
        />
        <span style={{ fontSize: 12, color: '#999', marginLeft: 16 }}>
          <span style={{ color: '#999' }}>▶</span> 工序流向 &nbsp;
          <span style={{ color: '#f5222d' }}>◆</span> 最后工序 &nbsp;
          <span style={{ color: '#595959' }}>—</span> FS &nbsp;
          <span style={{ color: '#1890ff' }}>---</span> SS &nbsp;
          <span style={{ color: '#52c41a' }}>···</span> FF &nbsp;
          <span style={{ color: '#fa8c16' }}>--·</span> SF
        </span>
      </Space>

      {/* 甘特图 */}
      {option ? (
        <ReactECharts option={option} notMerge style={{ height, width: '100%' }} opts={{ renderer: 'canvas' }} />
      ) : (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无排产数据</div>
      )}
    </div>
  );
};

export default GanttChart;
