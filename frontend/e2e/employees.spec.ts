import { test, expect, gotoApp, expectToast, field, uniqueSuffix } from './fixtures';

// "Employees" are User records (the model carries employee_id, job_title,
// badge_number, department, face_registered). Managed on the Users page.
test.describe('Employee (User) CRUD', () => {
  test('create, edit and delete an employee', async ({ page }) => {
    const suffix = uniqueSuffix();
    const username = `emp_${suffix}`.replace(/-/g, '_');
    const name = `Employee ${suffix}`;
    const email = `emp-${suffix}@e2e.example.com`;

    await gotoApp(page, '/users');

    // ---- Create ----
    await page.getByRole('button', { name: 'Add User' }).click();
    const createDialog = page.getByRole('dialog');
    await expect(createDialog.getByRole('heading', { name: 'Add User' })).toBeVisible();
    await field(createDialog, 'Full Name').fill(name);
    await field(createDialog, 'Email').fill(email);
    await field(createDialog, 'Username').fill(username);
    await field(createDialog, 'Password').fill('EmployeePass123!');
    await field(createDialog, 'Employee ID').fill(`EMP-${suffix}`);
    await field(createDialog, 'Job Title').fill('Security Analyst');
    await field(createDialog, 'Role').selectOption('security_officer');
    await createDialog.getByRole('button', { name: 'Create User' }).click();

    await expectToast(page, 'User created');
    const row = page.getByRole('row', { name: new RegExp(username) });
    await expect(row).toBeVisible();
    await expect(row).toContainText(name);
    await expect(row).toContainText('Security Analyst');

    // ---- Edit ----
    await row.getByRole('button', { name: 'Edit' }).click();
    const editDialog = page.getByRole('dialog');
    await expect(editDialog.getByRole('heading', { name: new RegExp(`Edit ${name}`) })).toBeVisible();
    await field(editDialog, 'Job Title').fill('Lead Analyst');
    await editDialog.getByRole('button', { name: 'Save Changes' }).click();

    await expectToast(page, 'User updated');
    await expect(page.getByRole('row', { name: new RegExp(username) })).toContainText('Lead Analyst');

    // ---- Delete ----
    await page.getByRole('row', { name: new RegExp(username) }).getByRole('button', { name: 'Delete' }).click();
    const deleteDialog = page.getByRole('dialog');
    await expect(deleteDialog.getByRole('heading', { name: 'Delete user?' })).toBeVisible();
    await deleteDialog.getByRole('button', { name: 'Delete' }).click();

    await expectToast(page, 'User deleted');
    await expect(page.getByRole('row', { name: new RegExp(username) })).toHaveCount(0);
  });
});
