import { Outlet, useNavigate } from "react-router-dom";

import { getSession, setSession } from "../api/client";

/** 管理端布局（SPEC 4.2）：顶栏 + 业务页面插槽；导航与角色裁剪随页面交付补齐。 */
export default function AppLayout() {
  const navigate = useNavigate();
  const session = getSession();

  function onLogout() {
    setSession(null); // 清除 JWT 会话 → 守卫随即弹回登录页
    navigate("/login", { replace: true });
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          padding: "12px 24px",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>部门智通 · 管理控制台</span>
        <span style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {session && (
            <small>
              {session.display_name || session.role}（{session.role}）
            </small>
          )}
          <button type="button" onClick={onLogout} style={{ padding: "4px 12px" }}>
            退出登录
          </button>
        </span>
      </header>
      <main style={{ padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
