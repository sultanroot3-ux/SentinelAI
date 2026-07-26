import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, gotoApp } from './fixtures';

const here = path.dirname(fileURLToPath(import.meta.url));
const FRAME = path.join(here, 'fixtures', 'frame.png');

test.describe('Face Recognition (Live Camera)', () => {
  test('live feed reports camera status', async ({ page }) => {
    await gotoApp(page, '/live');
    await expect(page.getByRole('heading', { name: 'Live Feed' })).toBeVisible();
    // No physical camera in CI -> "Camera Offline"; a dev machine may have one.
    // Either way the status badge must render deterministically.
    await expect(page.getByText(/Camera (Online|Offline)/)).toBeVisible();
  });

  test('snapshot recognition runs on an uploaded frame', async ({ page }) => {
    // The first recognition request loads the face model into memory. Where the
    // full InsightFace model is present (a typical dev machine) that cold start
    // can take tens of seconds; CI's OpenCV Haar fallback is fast. Allow ample
    // headroom so a real, slow-but-correct inference never reads as a failure.
    test.setTimeout(90_000);

    await gotoApp(page, '/live');

    // Upload a face-free frame through the hidden file input and analyze it.
    // The recognition endpoint runs for real (OpenCV Haar fallback when the
    // InsightFace model is absent, as in CI) and deterministically finds no
    // faces in a solid image.
    await page.locator('input[type="file"]').setInputFiles(FRAME);
    await page.getByRole('button', { name: 'Analyze Frame' }).click();

    // Longer timeout than the default: waits out the one-time model load above.
    await expect(page.getByRole('heading', { name: /face(s)? detected/ })).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByText('No faces found in this frame.')).toBeVisible();
  });
});
