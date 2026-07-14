import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
import packageJson from "./package.json";

export default defineConfig({
  define: {
    __REFLEX_APP_VERSION__: JSON.stringify(packageJson.version)
  },
  plugins: [svelte()],
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
});
