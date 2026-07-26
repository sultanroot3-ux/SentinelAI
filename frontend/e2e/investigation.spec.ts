import { test, expect, gotoApp, createEmployee } from './fixtures';

test.describe('Investigation Page', () => {
  test('the tool renders its controls', async ({ page }) => {
    await gotoApp(page, '/investigation');
    // Scope to page content (the top bar also renders an "Investigation" title).
    await expect(page.locator('.content').getByRole('heading', { name: 'Investigation' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Choose Image' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Run Investigation' })).toBeVisible();
  });

  test('an employee deep-link renders their database investigation report', async ({ page, request }) => {
    // Seed an employee via the API, then open the report deep-link that the
    // Users page's "Investigation report" action navigates to.
    const employee = await createEmployee(request, { job_title: 'Field Investigator' });

    await gotoApp(page, `/investigation?employee=${employee.id}`);

    await expect(page.getByRole('heading', { name: employee.name })).toBeVisible();
    await expect(page.getByText('Employee Profile (database record)')).toBeVisible();
    await expect(page.getByText(employee.employee_id)).toBeVisible();
    await expect(page.getByText('Registered employee')).toBeVisible();
  });
});
