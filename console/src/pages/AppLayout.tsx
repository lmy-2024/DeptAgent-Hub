import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { getSession, setSession } from "../api/client";

const navLink = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  padding: "6px 12px",
  borderRadius: 6,
  color: isActive ? "#1d4ed8" : "#374151",
  background: isActive ? "#eff6ff" : undefined,
  textDecoration: "none",
});

/** 管理端布局（SPEC 4.2）：顶栏 + 导航（按角色裁剪）+ 业务页面插槽。 */
export default function AppLayout() {
  const navigate = useNavigate();
  const session = getSession();
  const isAdmin = session?.role === "admin" || session?.role === "super";

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
      <nav
        style={{
          padding: "10px 24px",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <NavLink to="/" end style={navLink}>
          驾驶舱
        </NavLink>
        {isAdmin && (
          <NavLink to="/employees" style={navLink}>
            员工与设备
          </NavLink>
        )}
        {/* T1.10 台账 / T1.11 用量：交付后按 lead+ 渐次挂入（4.2 权限裁剪） */}
      </nav>
      <main style={{ padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
