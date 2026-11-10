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
