import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.GUIDESYNC_API_TARGET || "http://127.0.0.1:8770";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/config": apiTarget,
      "/docs": apiTarget,
      "/github": apiTarget,
      "/knowledge": apiTarget,
      "/openapi.json": apiTarget,
      "/projects": apiTarget,
      "/runs": apiTarget,
      "/settings": apiTarget
    }
  }
});
