import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(__dirname, '..', 'backend');

// Frontend (production build served by `vite preview`) and backend ports.
export const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT || 4173);
export const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT || 8000);
export const BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

// A dedicated, disposable SQLite database so E2E never touches dev/prod data.
// The backend server command deletes it (and its WAL/SHM/journal sidecars)
// before uvicorn starts, so every fresh backend boots a clean, freshly-seeded
// schema (deterministic). See the webServer definition for why this cleanup
// lives in the command and not in a globalSetup.
export const E2E_DB_PATH = path.join(backendDir, 'e2e_test.db');

// Persisted signed-in state (localStorage tokens) produced by auth.setup.ts and
// reused by every authenticated spec so we log in through the UI only once.
export const STORAGE_STATE = path.join(__dirname, 'e2e', '.auth', 'state.json');

// Which Python runs the backend. Precedence: explicit E2E_BACKEND_PYTHON, then
// the repo's backend/.venv (so `npx playwright test` works locally with no env
// vars), then a bare `python` — correct in CI, where setup-python installs deps
// against the system interpreter. Override E2E_BACKEND_PYTHON to point elsewhere.
function resolveBackendPython(): string {
  if (process.env.E2E_BACKEND_PYTHON) return process.env.E2E_BACKEND_PYTHON;
  const venvPython = path.join(backendDir, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  return 'python';
}
const backendPython = resolveBackendPython();

// Backend env: throwaway SQLite, a fixed dev-grade secret, development mode
// (production mode refuses the dev secret / SQLite — see config.py).
// E2E_DB_GLOB (db file + WAL/SHM/journal sidecars) is consumed by the reset
// step prepended to the backend command below.
const backendEnv = {
  ...process.env,
  SENTINEL_ENV: 'development',
  SENTINEL_DATABASE_URL: `sqlite:///${E2E_DB_PATH}`,
  SENTINEL_SECRET_KEY: 'e2e-secret-key-not-for-production-use-only',
  SENTINEL_DATABASE_DIR: backendDir,
  E2E_DB_GLOB: `${E2E_DB_PATH}*`,
  PYTHONUNBUFFERED: '1',
};

// Delete any leftover E2E database *before* uvicorn imports the app and opens
// the file. Passing the glob via env sidesteps shell-quoting the space-laden
// path. This intentionally runs in the server command rather than a Playwright
// globalSetup: globalSetup executes *after* the webServer boots, so it would
// unlink the DB the backend already has open — SQLite then fails every write
// with "attempt to write a readonly database". With reuseExistingServer (local,
// non-CI) the command isn't re-run, so a reused backend keeps its DB.
const resetDbCmd =
  `"${backendPython}" -c "import glob,os; [os.remove(f) for f in glob.glob(os.environ['E2E_DB_GLOB'])]"`;

export default defineConfig({
  testDir: './e2e',
  // Deterministic: one worker, no cross-spec DB write interleaving.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // CI infra can hiccup (network, cold browser); one retry absorbs that without
  // masking real product failures, which fail identically on the retry.
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }], ['list']]
    : [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // No camera/mic hardware in CI; grant permissions up-front so getUserMedia
    // paths (if hit) fail as "no device" rather than "permission prompt".
    permissions: [],
  },

  projects: [
    // 1) Log in once through the UI and save the authenticated storage state.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },

    // 2) Every other spec runs authenticated, reusing that state.
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: STORAGE_STATE },
      dependencies: ['setup'],
    },
  ],

  // Two servers, production-like: real uvicorn backend + the built frontend
  // bundle served by `vite preview` (which proxies /api to the backend).
  webServer: [
    {
      command: `${resetDbCmd} && "${backendPython}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: backendDir,
      url: `${BACKEND_URL}/api/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: backendEnv,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Bind preview to 127.0.0.1 explicitly: vite preview otherwise listens on
      // `localhost`, which macOS resolves to IPv6 (::1) first, so Playwright's
      // IPv4 readiness poll of BASE_URL (127.0.0.1) would time out.
      command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      url: BASE_URL,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { ...process.env, VITE_API_TARGET: BACKEND_URL },
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
});
