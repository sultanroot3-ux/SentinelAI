import { test as base, expect, type Page, type Locator, type APIRequestContext } from '@playwright/test';

export { expect };

/**
 * The default admin the backend seeds at startup. It is created with
 * must_change_password=true, so logging in through the UI lands on the
 * "set a new password" screen (exercised by login.spec.ts).
 */
export const DEFAULT_ADMIN = { username: 'admin', password: 'admin123' } as const;

/**
 * A dedicated admin created via the API in auth.setup.ts. It has
 * must_change_password=false, so it logs straight into the dashboard and is
 * used for every authenticated spec.
 */
// NOTE on email domains: the create-user API validates emails with pydantic's
// EmailStr, which rejects reserved special-use TLDs (.local, .test). The seeded
// default admin uses @sentinelai.local only because it's inserted directly via
// the model, bypassing that validation. Records created through the API must use
// a real, non-reserved domain — example.com (RFC 2606, reserved for testing).
export const E2E_ADMIN = {
  name: 'E2E Admin',
  email: 'e2e-admin@e2e.example.com',
  username: 'e2e_admin',
  password: 'E2eAdminPass123!',
} as const;

// Unique-suffix generator so records created by different specs/runs never
// collide (the backend enforces uniqueness on usernames, camera names, etc.).
let seq = 0;
export function uniqueSuffix(): string {
  seq += 1;
  return `${Date.now().toString(36)}-${seq}`;
}
export function uniqueName(prefix: string): string {
  return `${prefix}-${uniqueSuffix()}`;
}

/**
 * Locate a form control inside a modal/form by its visible label text. The
 * app's `.form-field` wraps a <label> and its <input>/<select>/<textarea> as
 * siblings (the label has no htmlFor), so we scope to the wrapping field.
 */
export function field(scope: Locator, label: string): Locator {
  // Match the wrapping .form-field by its exact <label> text — scoping to the
  // <label> element (not any text) avoids false matches on <option> labels such
  // as the "Employee" option inside a "Subject" <select>.
  return scope
    .locator(`.form-field:has(label:text-is(${JSON.stringify(label)}))`)
    .locator('input, select, textarea')
    .first();
}

// ---------------------------------------------------------------------------
// API helpers (used to bootstrap accounts/data deterministically, bypassing
// slow UI setup). Requests go through the preview server, which proxies /api
// to the backend — same path the browser uses.
// ---------------------------------------------------------------------------

export async function apiLogin(
  request: APIRequestContext,
  username: string,
  password: string
): Promise<string> {
  const res = await request.post('/api/auth/login', { data: { username, password } });
  expect(res.ok(), `login for ${username} failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return (await res.json()).access_token as string;
}

/** Idempotently create the E2E admin (bootstrapped from the seeded default admin). */
export async function ensureE2eAdmin(request: APIRequestContext): Promise<void> {
  const token = await apiLogin(request, DEFAULT_ADMIN.username, DEFAULT_ADMIN.password);
  const res = await request.post('/api/users', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: E2E_ADMIN.name,
      email: E2E_ADMIN.email,
      username: E2E_ADMIN.username,
      password: E2E_ADMIN.password,
      role: 'admin',
      department_id: 1,
      employee_id: 'EMP-E2E-ADMIN',
      access_level: 'full',
    },
  });
  // 201 created, or 422 if a previous run already created it — both are fine.
  // (422 is also how the API reports validation errors like a rejected email
  // domain, so we don't stop here: the login below is the real proof the admin
  // exists with the expected password, turning any masked failure into a clear
  // "login failed" rather than a silently-skipped setup.)
  expect(
    res.status() === 201 || res.status() === 422,
    `unexpected status creating e2e admin: ${res.status()} ${await res.text()}`
  ).toBeTruthy();
  // Confirm the account is actually usable (exists + password matches).
  await apiLogin(request, E2E_ADMIN.username, E2E_ADMIN.password);
}

/** Create an employee (User) via the API and return the created record. */
export async function createEmployee(
  request: APIRequestContext,
  overrides: Record<string, unknown> = {}
): Promise<any> {
  const token = await apiLogin(request, E2E_ADMIN.username, E2E_ADMIN.password);
  const suffix = uniqueSuffix();
  const res = await request.post('/api/users', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `Employee ${suffix}`,
      email: `employee-${suffix}@e2e.example.com`,
      username: `employee_${suffix}`.replace(/-/g, '_'),
      password: 'EmployeePass123!',
      role: 'receptionist',
      department_id: 1,
      employee_id: `EMP-${suffix}`,
      access_level: 'standard',
      job_title: 'QA Analyst',
      ...overrides,
    },
  });
  expect(res.status(), `create employee failed: ${await res.text()}`).toBe(201);
  return res.json();
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/** Fill the login form and submit; does not assert the outcome. */
export async function fillLogin(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: 'Sign In' }).click();
}

/** Log in and assert we land on the authenticated dashboard shell. */
export async function signIn(page: Page, username: string, password: string): Promise<void> {
  await fillLogin(page, username, password);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('link', { name: 'Live Camera' })).toBeVisible();
}

/** Open the top-right user menu and click Logout. */
export async function logoutViaMenu(page: Page): Promise<void> {
  await page.locator('.user-menu-trigger').click();
  await page.getByRole('button', { name: 'Logout' }).click();
}

/** Navigate to an in-app route via the URL and wait for the app shell. */
export async function gotoApp(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page.locator('.sidebar-nav')).toBeVisible();
}

/**
 * Assert a success toast with the given text is showing. Scopes to the toast's
 * text on purpose: toasts stack (each lingers ~3.8s — see Toast.jsx), so a
 * create-then-edit flow legitimately shows two `.toast-success` elements at
 * once. A bare `.toast-success` locator would then match several and trip
 * Playwright's strict-mode check.
 */
export async function expectToast(page: Page, text: string): Promise<void> {
  await expect(page.locator('.toast-success').filter({ hasText: text })).toBeVisible();
}

/**
 * Base test just re-exports Playwright's test. Authenticated storage state is
 * applied per-project in playwright.config.ts, so specs import `test` and get
 * a signed-in context automatically (except login/logout specs, which reset it).
 */
export const test = base;
