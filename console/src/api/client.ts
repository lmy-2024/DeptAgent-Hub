const TOKEN_KEY = "deptagent_token";

/** JWT 持有（SPEC 8.3 管理端 REST：Authorization: Bearer）。 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 8.5 统一错误体：{"error": {code, message, detail}}。 */
export interface ApiErrorBody {
  error: { code: string; message: string; detail?: unknown };
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, { ...init, headers });
  if (resp.status === 401) {
    setToken(null); // token 无效/过期/账号停用：清除并回登录页
    window.location.assign("/login");
    throw new Error("登录已失效，请重新登录");
  }
  if (!resp.ok) {
    let message = `请求失败（HTTP ${resp.status}）`;
    try {
      const body = (await resp.json()) as ApiErrorBody;
      if (body?.error?.message) message = body.error.message;
    } catch {
      /* 非 JSON 错误体：用缺省 message */
    }
    throw new Error(message);
  }
  return (await resp.json()) as T;
}

export function login(employeeNo: string, password: string) {
  return api<{ token: string; expires_at: string; role: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ employee_no: employeeNo, password }),
  });
}
