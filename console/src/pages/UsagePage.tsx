import { useCallback, useEffect, useMemo, useState } from "react";

import EChart from "../components/EChart";
import {
  type UsageAggregateResponse,
  type UsageDimension,
  type UsageGranularity,
  downloadUsageCsv,
  listUsageAggregate,
} from "../api/client";

const td: React.CSSProperties = { padding: "8px 12px", borderBottom: "1px solid #e5e7eb" };
const th: React.CSSProperties = {
  ...td,
  textAlign: "left",
  background: "#f9fafb",
  fontWeight: 600,
};

const DIMENSION_OPTIONS: { value: UsageDimension; text: string }[] = [
  { value: "employee", text: "按员工" },
  { value: "agent", text: "按智能体" },
  { value: "model", text: "按模型" },
  { value: "team", text: "按科室" },
];

const GRANULARITY_OPTIONS: { value: UsageGranularity; text: string }[] = [
  { value: "day", text: "日" },
  { value: "week", text: "周" },
  { value: "month", text: "月" },
];

/** 趋势图最多序列数（图例可读性），排行榜取前 10。 */
const TREND_MAX_SERIES = 8;
const RANKING_MAX_ROWS = 10;

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function localISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/** 用量分析页（SPEC 4.2 / 7.2，lead+）：四维 × 日/周/月聚合、排行榜、
 * CSV 导出（8.5）；成本折算列留阶段 2（4.2"成本折算 2"）。 */
export default function UsagePage() {
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<UsageAggregateResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const [dimension, setDimension] = useState<UsageDimension>("employee");
  const [granularity, setGranularity] = useState<UsageGranularity>("day");
  const today = useMemo(() => new Date(), []);
  const [fromDate, setFromDate] = useState(localISO(new Date(today.getTime() - 29 * 86_400_000)));
  const [toDate, setToDate] = useState(localISO(today));

  const load = useCallback(async () => {
    try {
      const resp = await listUsageAggregate({
        dimension,
        granularity,
        from_date: fromDate,
        to_date: toDate,
      });
      setData(resp);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [dimension, granularity, fromDate, toDate]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 时间轴 = 全成员桶并集（升序）；无数据成员补 0（聚合无行 = 0 用量）。 */
  const buckets = useMemo(() => {
    const all = new Set<string>();
    data?.series.forEach((m) => m.buckets.forEach((b) => all.add(b.bucket)));
    return [...all].sort();
  }, [data]);

  const trendOption = useMemo(() => {
    if (!data) return null;
    const top = data.series.slice(0, TREND_MAX_SERIES);
    return {
      tooltip: { trigger: "axis" },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 12 } },
      grid: { left: 70, right: 24, top: 24, bottom: 56 },
      xAxis: { type: "category", data: buckets },
      yAxis: { type: "value", name: "Token" },
      series: top.map((m) => ({
        name: m.label,
        type: "line" as const,
        smooth: true,
        symbolSize: 6,
        data: buckets.map((bk) => m.buckets.find((b) => b.bucket === bk)?.total_tokens ?? 0),
      })),
    };
  }, [data, buckets]);

  const rankingOption = useMemo(() => {
    if (!data) return null;
    const top = data.series.slice(0, RANKING_MAX_ROWS);
    return {
      tooltip: {},
      grid: { left: 170, right: 48, top: 16, bottom: 32 },
      xAxis: { type: "value" as const },
      yAxis: { type: "category" as const, data: top.map((m) => m.label).reverse() },
      series: [
        {
          type: "bar" as const,
          data: top.map((m) => m.total_tokens).reverse(),
          itemStyle: { color: "#3b82f6", borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right" as const, formatter: (p: { value: number }) => fmtTokens(p.value) },
        },
      ],
    };
  }, [data]);

  async function onExport() {
    setExporting(true);
    try {
      const blob = await downloadUsageCsv({
        dimension,
        granularity,
        from_date: fromDate,
        to_date: toDate,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage-${dimension}-${granularity}_${fromDate}_${toDate}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

  const rankingRows = data?.series.slice(0, RANKING_MAX_ROWS) ?? [];

  return (
    <div>
      <h2>用量分析</h2>
      {error && (
        <p role="alert" style={{ color: "#dc2626" }}>
          {error}
        </p>
      )}

      {/* ---- 维度 / 粒度 / 日期范围（4.2），切换即时生效 ---- */}
      <section style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          维度
          <select
            value={dimension}
            onChange={(e) => setDimension(e.target.value as UsageDimension)}
            style={{ padding: 6 }}
          >
            {DIMENSION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.text}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          粒度
          <select
            value={granularity}
            onChange={(e) => setGranularity(e.target.value as UsageGranularity)}
            style={{ padding: 6 }}
          >
            {GRANULARITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.text}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          从
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            style={{ padding: "4px 6px" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          至
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            style={{ padding: "4px 6px" }}
          />
        </label>
        <button type="button" onClick={() => void onExport()} disabled={exporting} style={{ padding: "6px 16px" }}>
          {exporting ? "导出中…" : "导出 CSV"}
        </button>
        <span style={{ color: "#6b7280", fontSize: 13 }}>
          {data ? `窗口 ${data.from_date} ~ ${data.to_date}，共 ${data.series.length} 项` : ""}
        </span>
      </section>

      {/* ---- 趋势图（Top 8 多序列，4.2 维度切换）---- */}
      <section style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Token 趋势（Top {TREND_MAX_SERIES}）</h3>
        {trendOption ? (
          <EChart option={trendOption} height={320} />
        ) : (
          <p style={{ color: "#6b7280" }}>暂无数据。</p>
        )}
      </section>

      {/* ---- 排行榜（4.2）：柱形图 + 明细表 ---- */}
      <section style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 420px", border: "1px solid #e5e7eb", borderRadius: 8, padding: 12 }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Token 排行（Top {RANKING_MAX_ROWS}）</h3>
          {rankingOption ? (
            <EChart option={rankingOption} height={Math.max(200, rankingRows.length * 36 + 60)} />
          ) : (
            <p style={{ color: "#6b7280" }}>暂无数据。</p>
          )}
        </div>
        <div style={{ flex: "1 1 420px", border: "1px solid #e5e7eb", borderRadius: 8, padding: 12 }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>明细</h3>
          {rankingRows.length > 0 ? (
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
              <thead>
                <tr>
                  <th style={th}>#</th>
                  <th style={th}>成员</th>
                  <th style={th}>Token</th>
                  <th style={th}>调用次数</th>
                  <th style={th}>活跃桶数</th>
                </tr>
              </thead>
              <tbody>
                {rankingRows.map((m, i) => (
                  <tr key={m.key}>
                    <td style={td}>{i + 1}</td>
                    <td style={td}>{m.label}</td>
                    <td style={td}>{fmtTokens(m.total_tokens)}</td>
                    <td style={td}>{m.call_count.toLocaleString()}</td>
                    <td style={td}>{m.buckets.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ color: "#6b7280" }}>暂无数据。</p>
          )}
        </div>
      </section>
    </div>
  );
}
