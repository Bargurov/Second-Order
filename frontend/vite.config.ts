import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two builds from one source tree (docs/admin-user-contract.md, section 11). `vite build` writes the Admin build
// (index.html) to dist/; `vite build --mode client` writes the Client build (client.html) to dist-client/. The server
// serves each role only its own build. Development only: the API runs separately (python -m second_order serve), and
// the dev server proxies /api to it; open /client.html for the Client.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: mode === "client"
    ? { outDir: "dist-client", emptyOutDir: true, rollupOptions: { input: "client.html" } }
    : { outDir: "dist", emptyOutDir: true },
}));
