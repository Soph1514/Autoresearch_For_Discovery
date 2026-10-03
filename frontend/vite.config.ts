import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: { main: "index.html", engine: "engine.html" } } },
  server: {
    proxy: { "/api": { target: process.env.RESEARCH_API_URL || "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
