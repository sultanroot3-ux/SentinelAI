import { test, expect, gotoApp, createEmployee } from './fixtures';

test.describe('Audit Logs', () => {
  test('an administrative action is recorded and searchable', async ({ page, request }) => {
    // Creating a user writes an audit event: user_create, detail contains the username.
    const employee = await createEmployee(request);

    await gotoApp(page, '/audit');
    await expect(page.locator('.data-table')).toBeVisible();

    // Search by the new username; the debounced query reloads the table.
    await page.getByPlaceholder('Detail or username…').fill(employee.username);

    const row = page.getByRole('row', { name: new RegExp(employee.username) });
    await expect(row).toBeVisible();
    await expect(row).toContainText('user_create');

    // Filtering by the user_create action keeps the row visible.
    await page.locator('select').first().selectOption('user_create');
    await expect(page.getByRole('row', { name: new RegExp(employee.username) })).toBeVisible();
  });
});
