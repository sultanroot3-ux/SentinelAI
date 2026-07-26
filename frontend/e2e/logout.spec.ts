import { test, expect, gotoApp, logoutViaMenu } from './fixtures';

test.describe('Logout', () => {
  test('logging out returns to login and blocks protected routes', async ({ page }) => {
    await gotoApp(page, '/');
    await logoutViaMenu(page);

    // Back on the login screen.
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();

    // A protected route now redirects to login instead of rendering.
    await page.goto('/users');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('.sidebar-nav')).toHaveCount(0);
  });
});
