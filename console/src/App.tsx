import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./pages/AppLayout";
import AgentsPage from "./pages/AgentsPage";
import DashboardPage from "./pages/DashboardPage";
import EmployeesPage from "./pages/EmployeesPage";
import UsagePage from "./pages/UsagePage";
import LoginPage from "./pages/LoginPage";
import { getSession, isSessionExpired } from "./api/client";

/** 路由守卫（JWT 持有/过期处理 SPEC 4.2）：无会话或已过期 → 登录页。 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (isSessionExpired(getSession())) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

// 路由骨架（SPEC 4.2 页面地图）：业务页面自阶段 1 起逐页挂入 AppLayout
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardIndex />} />
        <Route path="employees" element={<EmployeesPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="usage" element={<UsagePage />} />
      </Route>
    </Routes>
  );
}

/** 首页路由（4.2）：驾驶舱 lead+；member 无管理页可看 → 落地提示（不调
 * API，避免打开即 403；员工侧功能由插件内员工面板承接，T1.13 交付）。 */
function DashboardIndex() {
  const role = getSession()?.role;
  const isLead = role === "admin" || role === "super" || role === "lead";
  if (!isLead) {
    return (
      <div>
        <h2>部门智通 · 管理控制台</h2>
        <p>当前账号（{role}）暂无可用的管理页面；员工侧功能请使用插件内员工面板。</p>
      </div>
    );
  }
  return <DashboardPage />;
}
