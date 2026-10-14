import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" keeps every asset URL relative, required behind Home Assistant Ingress
export default defineConfig({
  base: "./",
  build: { chunkSizeWarningLimit: 1000 },
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8099" },
  },
});
