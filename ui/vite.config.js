import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During local development / browser tests, /api is proxied to the Flask
// service. Inside Docker, nginx performs the same proxying.
const apiTarget = process.env.VITE_API_TARGET || "http://localhost:5000";

const proxyConfig = {
  "/api": { target: apiTarget, changeOrigin: true },
  "/health": { target: apiTarget, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: proxyConfig,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    proxy: proxyConfig,
  },
});
