import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./pages/AppLayout";
import AgentsPage from "./pages/AgentsPage";
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
        <Route index element={<HomePlaceholder />} />
        <Route path="employees" element={<EmployeesPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="usage" element={<UsagePage />} />
        {/* T1.12 驾驶舱（index 替换占位）… */}
      </Route>
    </Routes>
  );
}

/** 首页占位（驾驶舱 T1.12 交付后替换）。 */
function HomePlaceholder() {
  return (
    <div>
      <h2>部门智通 · 管理控制台</h2>
      <p>驾驶舱建设中（T1.12）。请从导航进入已交付页面。</p>
    </div>
  );
}
