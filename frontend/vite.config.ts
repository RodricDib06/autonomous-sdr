import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/auth": { target: "http://localhost:8000", changeOrigin: true },
      "/leads": { target: "http://localhost:8000", changeOrigin: true },
      "/config": { target: "http://localhost:8000", changeOrigin: true },
      "/validate": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
