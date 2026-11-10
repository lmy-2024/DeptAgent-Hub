import { useCallback, useEffect, useMemo, useState } from "react";

import EChart from "../components/EChart";
import { type DashboardResponse, getDashboard } from "../api/client";

const td: React.CSSProperties = { padding: "8px 12px", borderBottom: "1px solid #e5e7eb" };
const th: React.CSSProperties = {
  ...td,
  textAlign: "left",
  background: "#f9fafb",
  fontWeight: 600,
};

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

/** last_heartbeat 为 ISO 带时区偏移（telemetry 上报时间）；null = 从未上报。 */
function fmtHeartbeat(iso: string | null): string {
  if (!iso) return "从未上报";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "从未上报";
  return new Date(t).toLocaleString("zh-CN", { hour12: false });
}

/** 驾驶舱（SPEC 4.2，lead+）：KPI 四卡 + 离线设备告警（3.4：主动暂停 ≠ 离线）+
 * 近 30 天 Token 趋势 + 科室 Top 榜；成本折算留阶段 2（无单价表宁缺毋滥）。 */
export default function DashboardPage() {
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getDashboard());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const kpis = useMemo(
    () =>
      data
        ? [
            { label: "智能体总数", value: data.agents_total.toLocaleString(), hint: "台账累计" },
            { label: "活跃智能体", value: data.agents_active_30d.toLocaleString(), hint: "近 30 天有上报" },
            { label: "本月 Token", value: fmtTokens(data.month_tokens), hint: "含缓存读写" },
            { label: "活跃员工", value: data.employees_active_30d.toLocaleString(), hint: "近 30 天有上报" },
          ]
        : [],
    [data],
  );

  const trendOption = useMemo(() => {
    if (!data) return null;
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 70, right: 24, top: 32, bottom: 32 },
      xAxis: { type: "category", data: data.trend.map((p) => p.date) },
      yAxis: { type: "value", name: "Token" },
      series: [
        {
          name: "Token 总量",
          type: "line" as const,
          smooth: true,
          symbolSize: 4,
          areaStyle: { opacity: 0.12 },
          data: data.trend.map((p) => p.total_tokens),
        },
      ],
    };
  }, [data]);

  const teamTopOption = useMemo(() => {
    if (!data || data.team_top.length === 0) return null;
    const top = data.team_top.slice(0, 10);
    return {
      tooltip: {},
      grid: { left: 140, right: 48, top: 32, bottom: 32 },
      xAxis: { type: "value" as const },
      yAxis: { type: "category" as const, data: top.map((t) => t.team).reverse() },
      series: [
        {
          type: "bar" as const,
          data: top.map((t) => t.total_tokens).reverse(),
          itemStyle: { color: "#10b981", borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: "right" as const,
            formatter: (p: { value: number }) => fmtTokens(p.value),
          },
        },
      ],
    };
  }, [data]);

  return (
    <div>
      <header style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>驾驶舱</h2>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </header>

      {error && (
        <p role="alert" style={{ color: "#dc2626", padding: "10px 12px", background: "#fef2f2", borderRadius: 8 }}>
          {error}
        </p>
      )}

      {data && (
        <>
          {/* KPI 四卡（4.2） */}
          <section
            aria-label="KPI 概览"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: 16,
              marginBottom: 24,
            }}
          >
            {kpis.map((kpi) => (
              <div
                key={kpi.label}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 10,
                  padding: "16px 20px",
                  background: "#fff",
                }}
              >
                <div style={{ fontSize: 13, color: "#6b7280" }}>{kpi.label}</div>
                <div style={{ fontSize: 30, fontWeight: 700, margin: "6px 0 4px" }}>{kpi.value}</div>
                <div style={{ fontSize: 12, color: "#9ca3af" }}>{kpi.hint}</div>
              </div>
            ))}
          </section>

          {/* 离线设备告警（4.2 / 3.4：排除 reporting_paused=1） */}
          <section
            aria-label="离线设备告警"
            style={{
              border: `1px solid ${data.offline_devices.length > 0 ? "#fca5a5" : "#d1fae5"}`,
              borderRadius: 10,
              padding: "12px 16px",
              marginBottom: 24,
              background: data.offline_devices.length > 0 ? "#fef2f2" : "#f0fdf4",
            }}
          >
            <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>
              离线设备告警（{data.offline_devices.length}）
            </h3>
            {data.offline_devices.length === 0 ? (
              <p style={{ margin: 0, color: "#059669" }}>
                全部在线设备状态正常（超 15 分钟无心跳的设备为 0；主动暂停上报的设备不参与判定）。
              </p>
            ) : (
              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={th}>设备</th>
                    <th style={th}>员工</th>
                    <th style={th}>工号</th>
                    <th style={th}>科室</th>
                    <th style={th}>最后心跳</th>
                  </tr>
                </thead>
                <tbody>
                  {data.offline_devices.map((d) => (
                    <tr key={d.device_id}>
                      <td style={td}>{d.device_name ?? "（未命名设备）"}</td>
                      <td style={td}>{d.user_name}</td>
                      <td style={td}>{d.employee_no}</td>
                      <td style={td}>{d.team ?? "—"}</td>
                      <td style={{ ...td, color: "#dc2626" }}>{fmtHeartbeat(d.last_heartbeat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* 趋势 + 科室 Top（4.2） */}
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
            <section aria-label="Token 趋势" style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12 }}>
              <h3 style={{ margin: "0 0 4px", fontSize: 15 }}>近 30 天 Token 趋势</h3>
              {trendOption && <EChart option={trendOption} height={300} />}
            </section>
            <section aria-label="科室 Top" style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12 }}>
              <h3 style={{ margin: "0 0 4px", fontSize: 15 }}>科室 Token Top（近 30 天）</h3>
              {teamTopOption ? (
                <EChart option={teamTopOption} height={300} />
              ) : (
                <p style={{ color: "#9ca3af", fontSize: 13 }}>窗口内暂无用量数据</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
