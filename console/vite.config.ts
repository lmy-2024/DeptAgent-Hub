import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发态将 /api 代理到本机 server（SPEC 4.1：零安装浏览器访问）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
