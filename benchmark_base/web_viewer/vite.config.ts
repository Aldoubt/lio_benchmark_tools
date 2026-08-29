import {defineConfig} from "vite";
import wasm from "vite-plugin-wasm";

export default defineConfig({
  // ES2022 already supports top-level await. Keeping the extra
  // vite-plugin-top-level-await compatibility transform here caused its
  // CommonJS bundle to require a standalone `rollup` package under Vite 8,
  // even though Vite 8 itself uses Rolldown. The Rerun WebViewer target is
  // modern Chromium/Firefox, so native ES2022 TLA is the simpler contract.
  plugins: [wasm()],
  optimizeDeps: {
    exclude: ["@rerun-io/web-viewer"],
  },
  build: {
    target: "es2022",
  },
});
