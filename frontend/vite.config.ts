import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Builds src/brand-list/main.tsx into main/static/js/brand-list.js, which the
// Django /brand/ page loads. Styles are not bundled: the component uses the
// classes compiled from scss/ (main.css), so it shares the site's tokens.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../main/static",
    emptyOutDir: false, // main/static/css is written by Sass
    copyPublicDir: false,
    sourcemap: true,
    rollupOptions: {
      input: "src/brand-list/main.tsx",
      output: {
        // Stable name so the Django template can reference it.
        entryFileNames: "js/brand-list.js",
        chunkFileNames: "js/[name].js",
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
});
