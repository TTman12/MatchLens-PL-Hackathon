import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { createReadStream, cpSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// The player reads match data through the shared contracts, either from files laid out
// like data/sample/ under /data/<name>/, or from a `matchlens-live` server under /live/.
// This plugin serves the repo's data/ folder in dev and copies the sample, and the demo
// match when it has been built, into the build, so the static site works on its own
// (Azure Static Web Apps, or `npm run preview`).
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
      for (const name of ["sample", "demo"]) {
        const from = path.join(dataRoot, name);
        if (!existsSync(path.join(from, "frames.jsonl"))) continue;
        cpSync(from, path.resolve(here, "dist/data", name), {
          recursive: true,
          filter: (src: string) => !src.endsWith("README.md"),
        });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), matchData()],
  // `matchlens-live` serves the live feed on :8000; `npm run dev` forwards /live/ to it.
  server: { proxy: { "/live": process.env.MATCHLENS_LIVE_URL ?? "http://127.0.0.1:8000" } },
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
