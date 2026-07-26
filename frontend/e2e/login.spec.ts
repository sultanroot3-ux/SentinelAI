import { test, expect, fillLogin, signIn, DEFAULT_ADMIN, E2E_ADMIN, uniqueSuffix } from './fixtures';

// Login runs unauthenticated — drop the shared signed-in storage state.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe('Login', () => {
  test('valid credentials sign the user into the dashboard', async ({ page }) => {
    await signIn(page, E2E_ADMIN.username, E2E_ADMIN.password);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('.topbar-title')).toHaveText('Dashboard');
    // The user's name is shown in the top-right menu once authenticated.
    await expect(page.locator('.user-menu-trigger')).toContainText(E2E_ADMIN.name);
  });

  test('invalid credentials show an error and stay on the login page', async ({ page }) => {
    // A throwaway username so we never trip the real accounts' rate limiter.
    await fillLogin(page, `nobody_${uniqueSuffix()}`, 'wrong-password');
    await expect(page.locator('.error-text')).toContainText('Invalid username or password');
    await expect(page).toHaveURL(/\/login$/);
  });

  test('seeded default admin is forced to change its password on first login', async ({ page }) => {
    // Valid default credentials, but the account is flagged must_change_password,
    // so the app gates on the "set a new password" screen instead of the dashboard.
    // (We intentionally do not complete the change — admin/admin123 must remain
    // valid for bootstrapping the E2E admin.)
    await fillLogin(page, DEFAULT_ADMIN.username, DEFAULT_ADMIN.password);
    await expect(
      page.getByText('You must set a new password before continuing')
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'Dashboard' })).toHaveCount(0);
  });
});
