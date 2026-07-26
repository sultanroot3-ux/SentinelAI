import { test, expect, gotoApp, expectToast, field, createEmployee, uniqueName } from './fixtures';

test.describe('Watchlists', () => {
  test('create a watchlist, add and remove an employee entry, then delete it', async ({ page, request }) => {
    // Seed an employee to place on the watchlist (created before the page loads
    // so it appears in the Employee <select>).
    const employee = await createEmployee(request);
    const listName = uniqueName('Watchlist');

    await gotoApp(page, '/watchlists');

    // ---- Create list ----
    await page.getByRole('button', { name: 'New Watchlist' }).click();
    const createDialog = page.getByRole('dialog');
    await field(createDialog, 'Name').fill(listName);
    await field(createDialog, 'Description').fill('E2E flagged persons');
    await field(createDialog, 'Alert level').selectOption('alert');
    await createDialog.getByRole('button', { name: 'Create' }).click();

    await expectToast(page, 'Watchlist created');
    const card = page.locator('.watchlist-card', { hasText: listName });
    await expect(card).toBeVisible();

    // ---- Add an employee entry ----
    await card.getByRole('button', { name: 'Add Entry' }).click();
    const entryDialog = page.getByRole('dialog');
    await expect(entryDialog.getByRole('heading', { name: new RegExp(`Add entry to`) })).toBeVisible();
    await field(entryDialog, 'Subject').selectOption('employee');
    await field(entryDialog, 'Employee').selectOption({ label: `${employee.name} (${employee.username})` });
    await field(entryDialog, 'Reason').fill('Repeated tailgating');
    await entryDialog.getByRole('button', { name: 'Add Entry' }).click();

    await expectToast(page, 'Entry added');
    const entry = card.locator('.watchlist-entry', { hasText: employee.name });
    await expect(entry).toBeVisible();
    await expect(entry).toContainText('Repeated tailgating');

    // ---- Remove the entry ----
    // The button's accessible name names the subject and the list, so a screen
    // reader user hearing a column of remove buttons can tell them apart.
    // Targeting it here doubles as the regression test for that label.
    await entry.getByRole('button', { name: `Remove ${employee.name}` }).click();
    const removeDialog = page.getByRole('dialog');
    await expect(removeDialog.getByRole('heading', { name: 'Remove entry?' })).toBeVisible();
    await removeDialog.getByRole('button', { name: 'Remove' }).click();
    await expectToast(page, 'Entry removed');
    await expect(card.locator('.watchlist-entry', { hasText: employee.name })).toHaveCount(0);

    // ---- Delete the watchlist ----
    await card.getByRole('button', { name: 'Delete watchlist' }).click();
    const deleteDialog = page.getByRole('dialog');
    await expect(deleteDialog.getByRole('heading', { name: 'Delete watchlist?' })).toBeVisible();
    await deleteDialog.getByRole('button', { name: 'Delete' }).click();
    await expectToast(page, 'Watchlist deleted');
    await expect(page.locator('.watchlist-card', { hasText: listName })).toHaveCount(0);
  });
});
