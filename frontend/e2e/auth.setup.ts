import { test as setup } from '@playwright/test';
import { ensureE2eAdmin, signIn, E2E_ADMIN } from './fixtures';
import { STORAGE_STATE } from '../playwright.config';

/**
 * One-time authentication. Creates the dedicated E2E admin (via API, bootstrapped
 * from the seeded default admin), logs in through the real login UI, and persists
 * the resulting localStorage tokens so authenticated specs skip the login step.
 */
setup('authenticate', async ({ page, request }) => {
  await ensureE2eAdmin(request);
  await signIn(page, E2E_ADMIN.username, E2E_ADMIN.password);
  await page.context().storageState({ path: STORAGE_STATE });
});
