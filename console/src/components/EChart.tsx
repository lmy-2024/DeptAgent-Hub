import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

// 按需注册（T1.11 拍板 ECharts）：用量页折线/柱状 + 驾驶舱（T1.12）复用
echarts.use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export type EChartsOption = echarts.EChartsCoreOption;

interface EChartProps {
  option: EChartsOption;
  /** 容器高度（px），宽度自适应父级。 */
  height?: number;
}

/** ECharts 薄包装：init/dispose 生命周期 + setOption + ResizeObserver 自适应。 */
export default function EChart({ option, height = 320 }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = echarts.init(el);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={containerRef} role="img" style={{ height, width: "100%" }} />;
}
