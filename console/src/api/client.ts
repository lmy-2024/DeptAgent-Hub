const TOKEN_KEY = "deptagent_token";

/** 登录会话（SPEC 8.3：token + expires_at UTC ISO + role；role 供后续页面导航裁剪）。 */
export interface Session {
  token: string;
  expires_at: string;
  role: string;
  display_name?: string | null;
}

export function getSession(): Session | null {
  const raw = localStorage.getItem(TOKEN_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw) as Session;
    return session.token ? session : null;
  } catch {
    return null; // 残留非法 JSON：视同未登录
  }
}

export function setSession(session: Session | null): void {
  if (session) localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
  else localStorage.removeItem(TOKEN_KEY);
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

/** JWT 过期判定（主动检查，路由守卫用；请求期 401 被动兜底见 api()）。 */
export function isSessionExpired(session: Session | null): boolean {
  if (!session) return true;
  const expires = Date.parse(session.expires_at);
  return Number.isNaN(expires) || expires <= Date.now();
}

/** 8.5 统一错误体：{"error": {code, message, detail}}。 */
export interface ApiErrorBody {
  error: { code: string; message: string; detail?: unknown };
}

/** API 调用错误（message 为服务端 8.5 中文文案，缺省 HTTP 状态兜底）。 */
export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { auth?: boolean },
): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, { ...init, headers });
  if (resp.ok) {
    return (await resp.json()) as T;
  }
  let message = `请求失败（HTTP ${resp.status}）`;
  let code: string | undefined;
  try {
    const body = (await resp.json()) as ApiErrorBody;
    if (body?.error?.message) message = body.error.message;
    code = body?.error?.code;
  } catch {
    /* 非 JSON 错误体：用缺省 message */
  }
  if (resp.status === 401 && options?.auth !== false) {
    // 管理端 JWT 无效/过期/账号停用（8.5 auth_failed）：清除并回登录页；
    // 登录请求本身（auth: false）不走此分支——文案直接抛给表单展示
    setSession(null);
    window.location.assign("/login");
    throw new ApiRequestError("登录已失效，请重新登录", 401);
  }
  throw new ApiRequestError(message, resp.status, code);
}

/** 带 JWT 的管理端请求（SPEC 8.3：Authorization: Bearer）。 */
export function api<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init);
}

export interface LoginResponse {
  token: string;
  expires_at: string;
  role: string;
  display_name?: string | null;
}

/** 登录（8.3）：失败 401 auth_failed（含锁定文案）直接抛给表单，不触发全局跳转。 */
export function login(employeeNo: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>(
    "/api/v1/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ employee_no: employeeNo, password }),
    },
    { auth: false },
  );
}

// ---- 员工与设备管理（T1.9，SPEC 4.2 / 5.2 / 8.5 分页）----

export interface EmployeeItem {
  id: number;
  employee_no: string;
  name: string;
  display_name: string | null;
  role: string;
  team: string | null;
  status: string;
  created_at: string | null;
  device_count: number;
  device_active_count: number;
  last_heartbeat: string | null;
  online: boolean;
  reporting_paused_any: number;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListEmployeesQuery {
  page?: number;
  page_size?: number;
  team?: string;
  q?: string;
}

export function listEmployees(query: ListEmployeesQuery = {}): Promise<Paged<EmployeeItem>> {
  const search = new URLSearchParams();
  if (query.page) search.set("page", String(query.page));
  if (query.page_size) search.set("page_size", String(query.page_size));
  if (query.team) search.set("team", query.team);
  if (query.q) search.set("q", query.q);
  const qs = search.toString();
  return api(`/api/v1/admin/employees${qs ? `?${qs}` : ""}`);
}

export interface InvitationItem {
  code: string;
  team: string | null;
  role: string | null;
  expires_at: string | null;
  used_by: number | null;
  used_at: string | null;
}

export interface CreateInvitationInput {
  team?: string | null;
  role: "member" | "lead"; // admin+ 不经邀请码（SPEC 5.2）
  expires_hours?: number;
}

export function createInvitation(body: CreateInvitationInput): Promise<InvitationItem> {
  return api("/api/v1/admin/invitations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listInvitations(): Promise<{ items: InvitationItem[] }> {
  return api("/api/v1/admin/invitations");
}

export interface DeviceItem {
  id: number;
  device_name: string | null;
  os: string | null;
  client_version: string | null;
  plugin_version: string | null;
  status: string;
  reporting_paused: number | null;
  last_seq: number;
  last_format_probe: string | null;
  last_heartbeat: string | null;
  created_at: string | null;
  online: boolean;
}

export function listDevices(userId: number): Promise<{ items: DeviceItem[] }> {
  return api(`/api/v1/admin/employees/${userId}/devices`);
}

export function revokeDevice(
  deviceId: number,
): Promise<{ device_id: number; status: string; message: string }> {
  return api(`/api/v1/admin/devices/${deviceId}/revoke`, { method: "POST" });
}

// ---- 智能体台账（T1.10，SPEC 4.2 / 5.3 / 8.5 分页；lead+ 门槛）----

export interface AgentListItem {
  id: number;
  agent_key: string;
  name: string;
  description: string | null;
  status: string;
  shared: number;
  category: string | null;
  tags: string | null;
  definition_key: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  owner_user_id: number;
  owner_name: string;
  owner_employee_no: string;
  team: string | null;
  maintainer_user_id: number | null;
  maintainer_name: string | null;
  maintainer_employee_no: string | null;
  total_tokens: number;
}

export type AgentStatusFilter = "new" | "active" | "archived" | "blocked";

export interface ListAgentsQuery {
  page?: number;
  page_size?: number;
  sort?: string;
  status?: AgentStatusFilter;
  team?: string;
  q?: string;
}

export function listAgents(query: ListAgentsQuery = {}): Promise<Paged<AgentListItem>> {
  const search = new URLSearchParams();
  if (query.page) search.set("page", String(query.page));
  if (query.page_size) search.set("page_size", String(query.page_size));
  if (query.sort) search.set("sort", query.sort);
  if (query.status) search.set("status", query.status);
  if (query.team) search.set("team", query.team);
  if (query.q) search.set("q", query.q);
  const qs = search.toString();
  return api(`/api/v1/admin/agents${qs ? `?${qs}` : ""}`);
}

export interface UsagePoint {
  stat_date: string;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  call_count: number;
  total_tokens: number;
}

export interface UsageSummary {
  total_tokens: number;
  call_count: number;
  days: number;
}

export interface TimelineEvent {
  at: string;
  event: string;
  label: string;
}

/** 详情抽屉数据源（4.2）：基础字段同列表 + 用量序列/汇总/时间线。 */
export interface AgentDetailResponse extends AgentListItem {
  usage_series: UsagePoint[];
  usage_summary: UsageSummary;
  timeline: TimelineEvent[];
}

export function getAgent(agentId: number): Promise<AgentDetailResponse> {
  return api(`/api/v1/admin/agents/${agentId}`);
}

// ---- 用量分析（T1.11，SPEC 4.2 / 7.2 / 8.5；lead+ 门槛）----

export interface UsageBucket {
  bucket: string;
  total_tokens: number;
  call_count: number;
}

export interface UsageSeriesItem {
  /** 聚合成员（key=维度键，label=展示名）；series 本身即排行榜（降序）。 */
  key: string;
  label: string;
  total_tokens: number;
  call_count: number;
  buckets: UsageBucket[];
}

export interface UsageAggregateResponse {
  dimension: string;
  granularity: string;
  from_date: string;
  to_date: string;
  series: UsageSeriesItem[];
}

export type UsageDimension = "employee" | "agent" | "model" | "team";
export type UsageGranularity = "day" | "week" | "month";

export interface UsageQuery {
  dimension?: UsageDimension;
  granularity?: UsageGranularity;
  from_date?: string;
  to_date?: string;
}

function usageParams(query: UsageQuery): URLSearchParams {
  const search = new URLSearchParams();
  if (query.dimension) search.set("dimension", query.dimension);
  if (query.granularity) search.set("granularity", query.granularity);
  if (query.from_date) search.set("from_date", query.from_date);
  if (query.to_date) search.set("to_date", query.to_date);
  return search;
}

export function listUsageAggregate(query: UsageQuery = {}): Promise<UsageAggregateResponse> {
  const qs = usageParams(query).toString();
  return api(`/api/v1/admin/usage/aggregate${qs ? `?${qs}` : ""}`);
}

/** CSV 导出（SPEC 8.5 BOM + CRLF）：JWT 需 header，不能裸 <a href>，blob 下载。 */
export async function downloadUsageCsv(query: UsageQuery = {}): Promise<Blob> {
  const qs = usageParams(query).toString();
  const resp = await fetch(`/api/v1/admin/usage/export${qs ? `?${qs}` : ""}`, {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  });
  if (resp.ok) return resp.blob();
  let message = `导出失败（HTTP ${resp.status}）`;
  try {
    const body = (await resp.json()) as ApiErrorBody;
    if (body?.error?.message) message = body.error.message;
  } catch {
    /* 非 JSON 错误体：用缺省 message */
  }
  if (resp.status === 401) {
    setSession(null);
    window.location.assign("/login");
  }
  throw new ApiRequestError(message, resp.status);
}

// ---- 驾驶舱（T1.12，SPEC 4.2 / 3.4；lead+ 门槛）----

export interface OfflineDevice {
  device_id: number;
  device_name: string | null;
  user_id: number;
  user_name: string;
  employee_no: string;
  team: string | null;
  last_heartbeat: string | null;
}

export interface TrendPoint {
  date: string;
  total_tokens: number;
}

export interface TeamTopItem {
  team: string;
  total_tokens: number;
}

/** 驾驶舱（4.2）：KPI 四卡 + 离线告警（3.4 排除主动暂停）+ 30 天趋势 + 科室 Top。 */
export interface DashboardResponse {
  agents_total: number;
  agents_active_30d: number;
  month_tokens: number;
  employees_active_30d: number;
  offline_devices: OfflineDevice[];
  trend: TrendPoint[];
  team_top: TeamTopItem[];
}

export function getDashboard(): Promise<DashboardResponse> {
  return api("/api/v1/admin/dashboard");
}
