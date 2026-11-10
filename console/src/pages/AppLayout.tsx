import { Outlet } from "react-router-dom";

/** 管理端布局骨架（阶段 0）：导航与角色裁剪随页面交付补齐（SPEC 4.2）。 */
export default function AppLayout() {
  return (
    <div style={{ fontFamily: "system-ui, sans-serif" }}>
      <header style={{ padding: "12px 24px", borderBottom: "1px solid #e5e7eb" }}>
        部门智通 · 管理控制台
      </header>
      <main style={{ padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
