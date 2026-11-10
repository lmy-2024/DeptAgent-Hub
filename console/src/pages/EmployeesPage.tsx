import { Fragment, useCallback, useEffect, useState } from "react";

import {
  type DeviceItem,
  type EmployeeItem,
  type InvitationItem,
  ApiRequestError,
  createInvitation,
  listDevices,
  listEmployees,
  listInvitations,
  revokeDevice,
} from "../api/client";

const td: React.CSSProperties = { padding: "8px 12px", borderBottom: "1px solid #e5e7eb" };
const th: React.CSSProperties = {
  ...td,
  textAlign: "left",
  background: "#f9fafb",
  fontWeight: 600,
};

/** 心跳灯（SPEC 4.2）：在线 = 任一设备 15 分钟内心跳（服务端判定）。 */
function Heartbeat({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      title={label}
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: on ? "#16a34a" : "#d1d5db",
        marginRight: 6,
      }}
    />
  );
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** 剩余有效期（未用未过期 → “剩 x 小时”；过期 → “已过期”）。 */
function remaining(expiresAt: string | null): string {
  if (!expiresAt) return "—";
  const hours = (Date.parse(expiresAt) - Date.now()) / 3_600_000;
  if (hours <= 0) return "已过期";
  return `剩 ${Math.round(hours)} 小时`;
}

const ROLE_TEXT: Record<string, string> = {
  member: "员工",
  lead: "领导",
  admin: "管理员",
  super: "超级管理员",
};

export default function EmployeesPage() {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // ---- 员工列表 ----
  const [employees, setEmployees] = useState<EmployeeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [teamInput, setTeamInput] = useState("");
  const [qInput, setQInput] = useState("");
  const [team, setTeam] = useState("");
  const [q, setQ] = useState("");

  // ---- 设备子表（展开行） ----
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  // ---- 邀请码 ----
  const [invitations, setInvitations] = useState<InvitationItem[]>([]);
  const [inviteTeam, setInviteTeam] = useState("");
  const [inviteRole, setInviteRole] = useState<"member" | "lead">("member");
  const [inviteHours, setInviteHours] = useState(72);
  const [lastCreated, setLastCreated] = useState<InvitationItem | null>(null);
  const [creating, setCreating] = useState(false);

  const loadEmployees = useCallback(async () => {
    try {
      const resp = await listEmployees({ page, page_size: pageSize, team, q });
      setEmployees(resp.items);
      setTotal(resp.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [page, team, q]);

  const loadInvitations = useCallback(async () => {
    try {
      const resp = await listInvitations();
      setInvitations(resp.items);
    } catch (err) {
      if (!(err instanceof ApiRequestError && err.status === 403)) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }, []);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);

  useEffect(() => {
    void loadInvitations();
  }, [loadInvitations]);

  async function toggleDevices(user: EmployeeItem) {
    if (expandedId === user.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(user.id);
    setDevices([]);
    try {
      const resp = await listDevices(user.id);
      setDevices(resp.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onRevoke(device: DeviceItem, owner: EmployeeItem) {
    if (
      !window.confirm(
        `确认吊销「${owner.name}（${owner.employee_no}）」的设备「${device.device_name ?? "未命名"}」？吊销后该设备上报立即失效。`,
      )
    ) {
      return;
    }
    setRevokingId(device.id);
    try {
      await revokeDevice(device.id);
      const resp = await listDevices(owner.id);
      setDevices(resp.items);
      await loadEmployees(); // 活跃设备数变化
      setNotice(`设备「${device.device_name ?? device.id}」令牌已吊销`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRevokingId(null);
    }
  }

  async function onCreateInvite(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      const item = await createInvitation({
        team: inviteTeam || null,
        role: inviteRole,
        expires_hours: inviteHours,
      });
      setLastCreated(item);
      await loadInvitations();
      setNotice(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
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
      <h2>员工与设备</h2>
      {error && (
        <p role="alert" style={{ color: "#dc2626" }}>
          {error}
        </p>
      )}
      {notice && <p style={{ color: "#16a34a" }}>{notice}</p>}

      {/* ---- 邀请码面板（SPEC 5.2：科室 / 角色 member|lead / 有效期 / 一次性）---- */}
      <section
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          padding: 16,
          marginBottom: 24,
        }}
      >
        <h3 style={{ marginTop: 0 }}>邀请码</h3>
        <form
          onSubmit={onCreateInvite}
          style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}
        >
          <label>
            科室
            <input
              value={inviteTeam}
              onChange={(e) => setInviteTeam(e.target.value)}
              placeholder="如：财务科"
              style={{ display: "block", margin: "4px 0 0", padding: 6 }}
            />
          </label>
          <label>
            角色
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as "member" | "lead")}
              style={{ display: "block", margin: "4px 0 0", padding: 6 }}
            >
              <option value="member">员工（member）</option>
              <option value="lead">领导（lead）</option>
            </select>
          </label>
          <label>
            有效期（小时）
            <input
              type="number"
              min={1}
              max={720}
              value={inviteHours}
              onChange={(e) => setInviteHours(Number(e.target.value) || 72)}
              style={{ display: "block", margin: "4px 0 0", padding: 6, width: 90 }}
            />
          </label>
          <button type="submit" disabled={creating} style={{ padding: "7px 16px" }}>
            {creating ? "生成中…" : "生成邀请码"}
          </button>
        </form>

        {lastCreated && (
          <p
            style={{
              background: "#f0fdf4",
              border: "1px solid #bbf7d0",
              borderRadius: 6,
              padding: "8px 12px",
            }}
          >
            最新邀请码：<strong style={{ letterSpacing: 1 }}>{lastCreated.code}</strong>
            （{lastCreated.role === "lead" ? "领导" : "员工"}
            {lastCreated.team ? ` · ${lastCreated.team}` : ""} · {remaining(lastCreated.expires_at)}
            ）
            <button
              type="button"
              style={{ marginLeft: 12, padding: "2px 10px" }}
              onClick={() => void navigator.clipboard?.writeText(lastCreated.code)}
            >
              复制
            </button>
          </p>
        )}

        {invitations.length > 0 && (
          <table style={{ borderCollapse: "collapse", marginTop: 12, fontSize: 14 }}>
            <thead>
              <tr>
                <th style={th}>邀请码</th>
                <th style={th}>科室</th>
                <th style={th}>角色</th>
                <th style={th}>状态</th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((inv) => (
                <tr key={inv.code}>
                  <td style={{ ...td, fontFamily: "monospace" }}>{inv.code}</td>
                  <td style={td}>{inv.team ?? "—"}</td>
                  <td style={td}>{inv.role ? (ROLE_TEXT[inv.role] ?? inv.role) : "—"}</td>
                  <td style={td}>
                    {inv.used_by !== null
                      ? "已使用"
                      : remaining(inv.expires_at) === "已过期"
                        ? "已过期"
                        : `未使用（${remaining(inv.expires_at)}）`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ---- 员工列表（SPEC 4.2：角色 / 科室 / 心跳灯 / 已暂停状态）---- */}
      <section>
        <form onSubmit={onSearch} style={{ display: "flex", gap: 12, marginBottom: 12 }}>
          <input
            value={teamInput}
            onChange={(e) => setTeamInput(e.target.value)}
            placeholder="按科室过滤"
            style={{ padding: 6 }}
          />
          <input
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="搜索工号 / 姓名"
            style={{ padding: 6 }}
          />
          <button type="submit" style={{ padding: "6px 16px" }}>
            查询
          </button>
        </form>

        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead>
            <tr>
              <th style={th}>工号</th>
              <th style={th}>姓名</th>
              <th style={th}>角色</th>
              <th style={th}>科室</th>
              <th style={th}>状态</th>
              <th style={th}>心跳</th>
              <th style={th}>设备</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {employees.map((user) => (
              <Fragment key={user.id}>
                <tr style={{ background: user.status !== "active" ? "#fef2f2" : undefined }}>
                  <td style={td}>{user.employee_no}</td>
                  <td style={td}>
                    {user.name}
                    {user.display_name && user.display_name !== user.name && (
                      <small style={{ color: "#6b7280" }}>（{user.display_name}）</small>
                    )}
                  </td>
                  <td style={td}>{ROLE_TEXT[user.role] ?? user.role}</td>
                  <td style={td}>{user.team ?? "—"}</td>
                  <td style={td}>
                    {user.status === "active" ? "在职" : "已停用"}
                    {user.reporting_paused_any === 1 && (
                      <span
                        style={{
                          marginLeft: 6,
                          padding: "1px 6px",
                          background: "#fef3c7",
                          borderRadius: 4,
                          fontSize: 12,
                        }}
                      >
                        报告暂停
                      </span>
                    )}
                  </td>
                  <td style={td}>
                    <Heartbeat
                      on={user.online}
                      label={`最近心跳：${fmtTime(user.last_heartbeat)}`}
                    />
                    {user.online ? "在线" : "离线"}
                  </td>
                  <td style={td}>
                    {user.device_count === 0 ? "—" : `${user.device_active_count}/${user.device_count}`}
                  </td>
                  <td style={td}>
                    <button
                      type="button"
                      onClick={() => void toggleDevices(user)}
                      style={{ padding: "3px 10px" }}
                    >
                      {expandedId === user.id ? "收起" : "设备"}
                    </button>
                  </td>
                </tr>
                {expandedId === user.id && (
                  <tr>
                    <td colSpan={8} style={{ ...td, background: "#fafafa" }}>
                      <strong>设备子表（一人多机，令牌独立吊销）</strong>
                      {devices.length === 0 && <p style={{ color: "#6b7280" }}>加载中…</p>}
                      {devices.length > 0 && (
                        <table
                          style={{ borderCollapse: "collapse", marginTop: 8, width: "100%" }}
                        >
                          <thead>
                            <tr>
                              <th style={th}>设备名</th>
                              <th style={th}>系统</th>
                              <th style={th}>客户端 / 插件版本</th>
                              <th style={th}>状态</th>
                              <th style={th}>最近心跳</th>
                              <th style={th}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {devices.map((device) => (
                              <tr key={device.id}>
                                <td style={td}>
                                  <Heartbeat on={device.online} label={device.status} />
                                  {device.device_name ?? `#${device.id}`}
                                  {device.reporting_paused === 1 && (
                                    <small style={{ color: "#b45309" }}>（报告暂停）</small>
                                  )}
                                </td>
                                <td style={td}>{device.os ?? "—"}</td>
                                <td style={td}>
                                  {device.client_version ?? "—"} / {device.plugin_version ?? "—"}
                                </td>
                                <td style={td}>
                                  {device.status === "active" ? "活跃" : "已吊销"}
                                </td>
                                <td style={td}>{fmtTime(device.last_heartbeat)}</td>
                                <td style={td}>
                                  {device.status === "active" && (
                                    <button
                                      type="button"
                                      disabled={revokingId === device.id}
                                      onClick={() => void onRevoke(device, user)}
                                      style={{ padding: "3px 10px", color: "#dc2626" }}
                                    >
                                      {revokingId === device.id ? "吊销中…" : "吊销令牌"}
                                    </button>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {employees.length === 0 && !error && <p>无匹配员工。</p>}

        <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span>
            第 {page} / {totalPages} 页（共 {total} 人）
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
    </div>
  );
}
