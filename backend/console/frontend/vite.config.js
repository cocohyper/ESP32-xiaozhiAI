import { defineConfig } from "vite";
export default defineConfig({
  build: { outDir: "../static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8004",
      "/downloads": "http://127.0.0.1:8004",
    },
  },
});
