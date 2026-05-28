import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ADK api_server runs at :8000 and serves routes at the root (/run, /apps/...,
// /list-apps). Proxy those prefixes so the SPA can call the agent same-origin
// (no CORS config needed on the agent). Override the target with ADK_URL.
const ADK_URL = process.env.ADK_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bind all interfaces and accept any Host header so the dev server is
    // reachable remotely (server public IP / forwarded domain), not just
    // localhost. vite 5 otherwise 404s "host not allowed" for non-local hosts.
    host: true,
    allowedHosts: true,
    proxy: {
      "/run": { target: ADK_URL, changeOrigin: true },
      "/run_sse": { target: ADK_URL, changeOrigin: true },
      "/apps": { target: ADK_URL, changeOrigin: true },
      "/list-apps": { target: ADK_URL, changeOrigin: true },
      "/pipelines": { target: ADK_URL, changeOrigin: true },
    },
  },
});
