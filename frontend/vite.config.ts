import { defineConfig } from "vitest/config";

// The card ships inside the integration as one ES module that Home Assistant serves
// and every dashboard loads; Lit is bundled into it.
export default defineConfig({
  build: {
    lib: {
      entry: "src/zaragoza-open-data-card.ts",
      formats: ["es"],
      fileName: () => "zaragoza-open-data-card.js",
    },
    outDir: "../custom_components/zaragoza_open_data/frontend",
    // The folder holds nothing but the built card.
    emptyOutDir: true,
    copyPublicDir: false,
    // Lit's licence (BSD-3-Clause) asks for its notices to ship with the code.
    rolldownOptions: { output: { comments: { legal: true } } },
  },
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
    setupFiles: ["test/support/setup.ts"],
  },
});
