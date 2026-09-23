import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/catalog": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/api-proxy": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api-proxy/, ""),
      },
    },
  },
});
