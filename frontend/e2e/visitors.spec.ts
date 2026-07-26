import { test, expect, gotoApp, expectToast, field, uniqueSuffix } from './fixtures';

test.describe('Visitor CRUD', () => {
  test('register, edit and check in a visitor', async ({ page }) => {
    const suffix = uniqueSuffix();
    const name = `Visitor ${suffix}`;

    await gotoApp(page, '/visitors');

    // ---- Register (create) ----
    await page.getByRole('button', { name: 'Register Visitor' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Register Visitor' })).toBeVisible();
    await field(dialog, 'Full Name').fill(name);
    await field(dialog, 'Company').fill('Acme Corp');
    await field(dialog, 'Purpose of visit').fill('Interview');
    await dialog.getByRole('button', { name: 'Register' }).click();

    await expectToast(page, 'Visitor registered');
    const row = page.getByRole('row', { name: new RegExp(name) });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Acme Corp');
    await expect(row).toContainText('expected');

    // ---- Edit ----
    await row.getByRole('button', { name: 'Edit' }).click();
    const editDialog = page.getByRole('dialog');
    await field(editDialog, 'Company').fill('Globex Inc');
    await editDialog.getByRole('button', { name: 'Save Changes' }).click();
    await expectToast(page, 'Visitor updated');
    await expect(page.getByRole('row', { name: new RegExp(name) })).toContainText('Globex Inc');

    // ---- Check in (state transition recorded in access history) ----
    await page.getByRole('row', { name: new RegExp(name) }).getByRole('button', { name: 'Check in' }).click();
    const confirmDialog = page.getByRole('dialog');
    await expect(confirmDialog.getByRole('heading', { name: 'Check in visitor?' })).toBeVisible();
    await confirmDialog.getByRole('button', { name: 'Confirm' }).click();

    await expectToast(page, 'checked in');
    await expect(page.getByRole('row', { name: new RegExp(name) })).toContainText('checked in');
  });
});
