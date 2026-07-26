import { test, expect, gotoApp, expectToast, field, uniqueName } from './fixtures';

test.describe('Camera Management', () => {
  test('add, edit and delete a camera', async ({ page }) => {
    const name = uniqueName('cam');

    await gotoApp(page, '/cameras');

    // ---- Add ----
    await page.getByRole('button', { name: 'Add Camera' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Add Camera' })).toBeVisible();
    await field(dialog, 'Name').fill(name);
    await field(dialog, 'Source (device index or stream URL)').fill('rtsp://camera.example/stream1');
    await dialog.getByRole('button', { name: 'Create Camera' }).click();

    await expectToast(page, 'Camera created');
    const row = page.getByRole('row', { name: new RegExp(name) });
    await expect(row).toBeVisible();
    await expect(row).toContainText('rtsp://camera.example/stream1');
    await expect(row).toContainText('Active');

    // ---- Edit ----
    await row.getByRole('button', { name: 'Edit' }).click();
    const editDialog = page.getByRole('dialog');
    await field(editDialog, 'Source (device index or stream URL)').fill('rtsp://camera.example/stream2');
    await editDialog.getByRole('button', { name: 'Save Changes' }).click();
    await expectToast(page, 'Camera updated');
    await expect(page.getByRole('row', { name: new RegExp(name) })).toContainText('stream2');

    // ---- Delete ----
    await page.getByRole('row', { name: new RegExp(name) }).getByRole('button', { name: 'Delete' }).click();
    const deleteDialog = page.getByRole('dialog');
    await expect(deleteDialog.getByRole('heading', { name: 'Delete camera?' })).toBeVisible();
    await deleteDialog.getByRole('button', { name: 'Delete' }).click();

    await expectToast(page, 'Camera deleted');
    await expect(page.getByRole('row', { name: new RegExp(name) })).toHaveCount(0);
  });
});
