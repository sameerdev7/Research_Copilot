import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const django = "http://localhost:8000";

export default defineConfig(({ command }) => ({
  // Django serves the build under /static/
  base: command === "build" ? "/static/" : "/",
  plugins: [react()],
  test: { include: ["src/**/*.test.ts"] },
  server: {
    port: 5173,
    proxy: { "/api": django, "/admin": django, "/static": django },
  },
}));
