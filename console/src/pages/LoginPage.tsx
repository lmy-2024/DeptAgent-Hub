import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { getSession, isSessionExpired, login, setSession } from "../api/client";

/** 登录页（SPEC 4.2 页面地图：账号密码；错误文案 8.5 auth_failed）。 */
export default function LoginPage() {
  const navigate = useNavigate();
  const [employeeNo, setEmployeeNo] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 已持有效会话：无需重复登录，直达首页（路由守卫对偶）
  if (!isSessionExpired(getSession())) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await login(employeeNo, password);
      // 401 auth_failed（工号或密码不正确 / 失败次数过多已临时锁定）文案
      // 由 login() 原样抛出，此处直接展示（SPEC 8.5 中文 message）
      setSession({
        token: resp.token,
        expires_at: resp.expires_at,
        role: resp.role,
        display_name: resp.display_name,
      });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "system-ui, sans-serif" }}>
      <h2>登录 · 部门智通管理控制台</h2>
      <form onSubmit={onSubmit}>
        <label>
          工号
          <input
            value={employeeNo}
            onChange={(e) => setEmployeeNo(e.target.value)}
            autoComplete="username"
            autoFocus
            style={{ display: "block", width: "100%", margin: "4px 0 12px", padding: 8 }}
          />
        </label>
        <label>
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            style={{ display: "block", width: "100%", margin: "4px 0 12px", padding: 8 }}
          />
        </label>
        <button
          type="submit"
          disabled={busy || !employeeNo || !password}
          style={{ width: "100%", padding: 10 }}
        >
          {busy ? "登录中…" : "登录"}
        </button>
        {error && (
          <p role="alert" style={{ color: "#dc2626", margin: "12px 0 0" }}>
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
