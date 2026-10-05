import { defineConfig } from "@playwright/test";

const port = 8100;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  // the first question loads the embedding model
  expect: { timeout: 30_000 },
  use: { baseURL: `http://localhost:${port}` },
  // Django in demo mode, started by scripts/e2e.sh's environment
  webServer: {
    command: `uv run python manage.py runserver ${port} --noreload`,
    cwd: "..",
    url: `http://localhost:${port}/healthz`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
