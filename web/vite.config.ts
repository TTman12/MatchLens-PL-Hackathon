import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { createReadStream, cpSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// The player reads match data through the shared contracts. Until a live API exists, it
// loads files laid out like data/sample/ from /data/<name>/. This plugin serves the
// repo's data/ folder in dev and copies the sample into the build, so the static site
// works on its own (Azure Static Web Apps, or `npm run preview`).
const dataRoot = path.resolve(here, "../data");

function matchData(): Plugin {
  return {
    name: "matchlens-data",
    configureServer(server) {
      server.middlewares.use("/data", (req, res, next) => {
        const rel = decodeURIComponent((req.url ?? "/").split("?")[0] ?? "/");
        const file = path.join(dataRoot, rel);
        if (!file.startsWith(dataRoot) || !existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader("Content-Type", file.endsWith(".json") ? "application/json" : "text/plain");
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      const out = path.resolve(here, "dist/data/sample");
      cpSync(path.join(dataRoot, "sample"), out, {
        recursive: true,
        filter: (src: string) => !src.endsWith("README.md"),
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), matchData()],
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => (id.includes("node_modules/three") ? "three" : id.includes("node_modules") ? "vendor" : undefined),
      },
    },
  },
  test: { environment: "node" },
});
