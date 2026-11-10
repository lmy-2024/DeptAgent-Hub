import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./pages/AppLayout";
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
        {/* T1.9 员工与设备 / T1.10 台账 / T1.11 用量 / T1.12 驾驶舱 … */}
      </Route>
    </Routes>
  );
}
