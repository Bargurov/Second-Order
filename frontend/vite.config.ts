import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Dev proxy target — env-driven so running the backend on a different
// host / port during local dev doesn't require editing this file.
// Production builds never see this; the browser calls the URL returned
// by resolveApiBase() in src/lib/api.ts (driven by VITE_API_BASE_URL).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devBackend =
    env.VITE_DEV_API_PROXY_TARGET?.trim() || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      proxy: {
        // Dev-only rewrite: "/api/foo" → "<devBackend>/foo".  Keeps
        // every request same-origin from the browser's perspective so
        // CORS is never an issue during local development.  In prod
        // there is no proxy — the frontend hits VITE_API_BASE_URL
        // directly (default "/api", rewritten by the reverse proxy).
        "/api": {
          target: devBackend,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
      },
    },
  };
});
