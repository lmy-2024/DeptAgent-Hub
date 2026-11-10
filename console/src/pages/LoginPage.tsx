import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { login, setToken } from "../api/client";

/** 登录页（SPEC 4.2：0 端点 → 1 页面）。阶段 0 为可用最小版，T1.8 补全（过期处理/错误文案/锁定提示）。 */
export default function LoginPage() {
  const navigate = useNavigate();
  const [employeeNo, setEmployeeNo] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await login(employeeNo, password);
      setToken(token);
      navigate("/");
    } catch (message) {
      setError(String(message));
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
        {error && <p style={{ color: "#dc2626" }}>{error}</p>}
      </form>
    </div>
  );
}
