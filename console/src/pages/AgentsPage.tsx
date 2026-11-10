import { useCallback, useEffect, useState } from "react";

import {
  type AgentDetailResponse,
  type AgentListItem,
  type AgentStatusFilter,
  type TimelineEvent,
  type UsagePoint,
  getAgent,
  listAgents,
} from "../api/client";

const td: React.CSSProperties = { padding: "8px 12px", borderBottom: "1px solid #e5e7eb" };
const th: React.CSSProperties = {
  ...td,
  textAlign: "left",
  background: "#f9fafb",
  fontWeight: 600,
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

/** 状态徽标（5.3）：new=自动登记待确认 / active / archived / blocked。 */
const STATUS_META: Record<string, { text: string; bg: string; color: string }> = {
  new: { text: "待确认", bg: "#dbeafe", color: "#1d4ed8" },
  active: { text: "活跃", bg: "#dcfce7", color: "#15803d" },
  archived: { text: "已归档", bg: "#e5e7eb", color: "#374151" },
  blocked: { text: "已封停", bg: "#fee2e2", color: "#b91c1c" },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { text: status, bg: "#f3f4f6", color: "#374151" };
  return (
    <span
      style={{ padding: "2px 8px", borderRadius: 999, background: meta.bg, color: meta.color, fontSize: 12 }}
    >
      {meta.text}
    </span>
  );
}

/** 用量曲线（4.2 详情抽屉）：纯 SVG polyline，最近 90 天按日 total_tokens；
 * 图表库 T1.11 拍板后用量页统一替换，抽屉内联轻量实现即可。 */
function UsageSparkline({ series }: { series: UsagePoint[] }) {
  if (series.length === 0) return <p style={{ color: "#6b7280", margin: 0 }}>暂无用量数据</p>;
  const w = 380;
  const h = 90;
  const pad = 10;
  const max = Math.max(...series.map((p) => p.total_tokens), 1);
  const step = series.length > 1 ? (w - pad * 2) / (series.length - 1) : 0;
  const points = series.map((p, i) => ({
    x: pad + i * step,
    y: h - pad - (p.total_tokens / max) * (h - pad * 2),
    p,
  }));
  return (
    <svg width={w} height={h} role="img" aria-label="最近 90 天用量曲线">
      <polyline
        points={points.map((pt) => `${pt.x},${pt.y}`).join(" ")}
        fill="none"
        stroke="#2563eb"
        strokeWidth={2}
      />
      {points.map((pt) => (
        <circle key={pt.p.stat_date} cx={pt.x} cy={pt.y} r={3} fill="#2563eb">
          <title>{`${pt.p.stat_date}：${pt.p.total_tokens} tokens（${pt.p.call_count} 次调用）`}</title>
        </circle>
      ))}
    </svg>
  );
}

/** 变更时间线（4.2）：discovered / first_usage / last_usage / last_seen 快照节点。 */
function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {events.map((e) => (
        <li key={`${e.event}-${e.at}`} style={{ display: "flex", gap: 10, marginBottom: 12 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#3b82f6",
              flexShrink: 0,
              marginTop: 4,
            }}
          />
          <span>
            <span style={{ display: "block", fontSize: 13 }}>{e.label}</span>
            <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>
              {fmtTime(e.at)}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

const SORT_OPTIONS: { value: string; text: string }[] = [
  { value: "-last_seen_at", text: "最近上报 ↓" },
  { value: "last_seen_at", text: "最近上报 ↑" },
  { value: "-name", text: "名称 ↓" },
  { value: "name", text: "名称 ↑" },
  { value: "-first_seen_at", text: "首次发现 ↓" },
  { value: "first_seen_at", text: "首次发现 ↑" },
  { value: "-status", text: "状态 ↓" },
  { value: "status", text: "状态 ↑" },
];

const drawerDt: React.CSSProperties = {
  color: "#6b7280",
  fontSize: 12,
  marginBottom: 2,
};
const drawerDd: React.CSSProperties = {
  margin: "0 0 10px",
  fontSize: 14,
};

/** 智能体台账页（SPEC 4.2 / 5.3，lead+）：六列 + 筛选 + 详情抽屉；只读——
 * 治理动作（确认/归并/改派/归档/封停）与 CSV 导出留后续任务。 */
export default function AgentsPage() {
  const [error, setError] = useState<string | null>(null);

  // ---- 列表 + 筛选 ----
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [status, setStatus] = useState<AgentStatusFilter | "">("");
  const [sort, setSort] = useState("-last_seen_at");
  const [teamInput, setTeamInput] = useState("");
  const [qInput, setQInput] = useState("");
  const [team, setTeam] = useState("");
  const [q, setQ] = useState("");

  // ---- 详情抽屉 ----
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AgentDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadAgents = useCallback(async () => {
    try {
      const resp = await listAgents({
        page,
        page_size: pageSize,
        sort,
        status: status || undefined,
        team,
        q,
      });
      setAgents(resp.items);
      setTotal(resp.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [page, sort, status, team, q]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  async function openDetail(agent: AgentListItem) {
    setDetailId(agent.id);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await getAgent(agent.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }

  function onSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setTeam(teamInput.trim());
    setQ(qInput.trim());
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      <h2>智能体台账</h2>
      {error && (
        <p role="alert" style={{ color: "#dc2626" }}>
          {error}
        </p>
      )}

      {/* ---- 筛选（状态/排序立即生效；科室/关键词表单提交）---- */}
      <section>
        <form onSubmit={onSearch} style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            状态
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as AgentStatusFilter | "");
                setPage(1);
              }}
              style={{ padding: 6 }}
            >
              <option value="">全部</option>
              <option value="new">待确认</option>
              <option value="active">活跃</option>
              <option value="archived">已归档</option>
              <option value="blocked">已封停</option>
            </select>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            排序
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              style={{ padding: 6 }}
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.text}
                </option>
              ))}
            </select>
          </label>
          <input
            value={teamInput}
            onChange={(e) => setTeamInput(e.target.value)}
            placeholder="按科室过滤"
            style={{ padding: 6 }}
          />
          <input
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="搜索名称 / 描述 / agent_key"
            style={{ padding: 6 }}
          />
          <button type="submit" style={{ padding: "6px 16px" }}>
            查询
          </button>
        </form>

        {/* ---- 六列（4.2）+ Token 消耗（5.3 附加）---- */}
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead>
            <tr>
              <th style={th}>名称</th>
              <th style={th}>功能描述</th>
              <th style={th}>创建人</th>
              <th style={th}>维护人</th>
              <th style={th}>状态</th>
              <th style={th}>所属科室</th>
              <th style={th}>Token 消耗</th>
              <th style={th}>最近上报</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent.id}>
                <td style={td}>
                  {agent.name}
                  <span style={{ display: "block", fontFamily: "monospace", fontSize: 12, color: "#6b7280" }}>
                    {agent.agent_key}
                  </span>
                </td>
                <td style={td}>{agent.description ?? "—"}</td>
                <td style={td}>
                  {agent.owner_name}
                  <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>
                    {agent.owner_employee_no}
                  </span>
                </td>
                <td style={td}>
                  {agent.maintainer_name ? (
                    <>
                      {agent.maintainer_name}
                      <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>
                        {agent.maintainer_employee_no}
                      </span>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td style={td}>
                  <StatusBadge status={agent.status} />
                </td>
                <td style={td}>{agent.team ?? "—"}</td>
                <td style={td}>{fmtTokens(agent.total_tokens)}</td>
                <td style={td}>{fmtTime(agent.last_seen_at)}</td>
                <td style={td}>
                  <button
                    type="button"
                    onClick={() => void openDetail(agent)}
                    style={{ padding: "3px 10px" }}
                  >
                    详情
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {agents.length === 0 && !error && <p>无匹配智能体。</p>}

        <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span>
            第 {page} / {totalPages} 页（共 {total} 个）
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      </section>

      {/* ---- 详情抽屉（4.2：基础信息 + 用量曲线 + 时间线）---- */}
      {detailId !== null && (
        <div
          role="dialog"
          aria-label="智能体详情"
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", zIndex: 40 }}
          onClick={() => setDetailId(null)}
        >
          <aside
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              bottom: 0,
              width: 440,
              background: "#fff",
              boxShadow: "-4px 0 16px rgba(0,0,0,0.15)",
              overflowY: "auto",
              padding: 24,
              boxSizing: "border-box",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {detailLoading && <p>加载中…</p>}
            {!detailLoading && detail && (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <h3 style={{ margin: 0 }}>
                    {detail.name}
                    <span style={{ display: "block", fontFamily: "monospace", fontSize: 12, color: "#6b7280", fontWeight: 400 }}>
                      {detail.agent_key}
                    </span>
                  </h3>
                  <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <StatusBadge status={detail.status} />
                    <button type="button" onClick={() => setDetailId(null)} style={{ padding: "3px 10px" }}>
                      关闭
                    </button>
                  </span>
                </div>

                {/* 基础信息 */}
                <dl style={{ marginTop: 20 }}>
                  <dt style={drawerDt}>功能描述</dt>
                  <dd style={drawerDd}>{detail.description ?? "—"}</dd>
                  <dt style={drawerDt}>分类 / 标签</dt>
                  <dd style={drawerDd}>
                    {detail.category ?? "—"}
                    {detail.tags ? ` · ${detail.tags}` : ""}
                  </dd>
                  <dt style={drawerDt}>创建人</dt>
                  <dd style={drawerDd}>
                    {detail.owner_name}（{detail.owner_employee_no}）
                  </dd>
                  <dt style={drawerDt}>维护人</dt>
                  <dd style={drawerDd}>
                    {detail.maintainer_name
                      ? `${detail.maintainer_name}（${detail.maintainer_employee_no}）`
                      : "—"}
                  </dd>
                  <dt style={drawerDt}>所属科室</dt>
                  <dd style={drawerDd}>{detail.team ?? "—"}</dd>
                  <dt style={drawerDt}>共享 / 定义键</dt>
                  <dd style={drawerDd}>
                    {detail.shared === 1 ? "共享" : "个人"} · {detail.definition_key ?? "—"}
                  </dd>
                  <dt style={drawerDt}>首次发现 / 最近上报</dt>
                  <dd style={drawerDd}>
                    {fmtTime(detail.first_seen_at)} / {fmtTime(detail.last_seen_at)}
                  </dd>
                </dl>

                {/* 用量汇总 + 曲线 */}
                <h4 style={{ marginBottom: 8 }}>用量（全期 / 最近 90 天曲线）</h4>
                <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                  <span style={{ flex: 1, border: "1px solid #e5e7eb", borderRadius: 8, padding: "8px 12px" }}>
                    <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>累计 Token</span>
                    <strong>{fmtTokens(detail.usage_summary.total_tokens)}</strong>
                  </span>
                  <span style={{ flex: 1, border: "1px solid #e5e7eb", borderRadius: 8, padding: "8px 12px" }}>
                    <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>调用次数</span>
                    <strong>{detail.usage_summary.call_count.toLocaleString()}</strong>
                  </span>
                  <span style={{ flex: 1, border: "1px solid #e5e7eb", borderRadius: 8, padding: "8px 12px" }}>
                    <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>活跃天数</span>
                    <strong>{detail.usage_summary.days}</strong>
                  </span>
                </div>
                <UsageSparkline series={detail.usage_series} />

                {/* 时间线 */}
                <h4 style={{ marginBottom: 8, marginTop: 20 }}>时间线</h4>
                <Timeline events={detail.timeline} />
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
