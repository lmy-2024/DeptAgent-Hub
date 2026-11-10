import { Route, Routes } from "react-router-dom";

import AppLayout from "./pages/AppLayout";
import LoginPage from "./pages/LoginPage";

// 路由骨架（SPEC 4.2 页面地图）：业务页面自阶段 1 起逐页挂入 AppLayout
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<AppLayout />}>
        {/* T1.9 员工与设备 / T1.10 台账 / T1.11 用量 / T1.12 驾驶舱 … */}
      </Route>
    </Routes>
  );
}
