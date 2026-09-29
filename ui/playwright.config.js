import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
const API_TARGET = process.env.VITE_API_TARGET || "http://localhost:5000";

export default defineConfig({
  testDir: "./tests",
  timeout: 90000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "python3 -m gunicorn --bind 127.0.0.1:5000 'app.api:app'",
      cwd: "../backend",
      url: "http://localhost:5000/health",
      reuseExistingServer: true,
      timeout: 30000,
    },
    {
      command: `npm run preview -- --host 127.0.0.1 --port ${PORT}`,
      url: `http://localhost:${PORT}`,
      reuseExistingServer: true,
      timeout: 60000,
      env: { VITE_API_TARGET: API_TARGET },
    },
  ],
});
