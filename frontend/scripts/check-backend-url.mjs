/**
 * Vercel build guard: refuse to build while vercel.json still points at the
 * placeholder backend.
 *
 * Without this, a deploy succeeds and ships a UI that loads, shows a login form,
 * and then fails every single API call — a failure that looks like a backend
 * outage rather than a missing config line. Failing at build time with an
 * actionable message is cheaper than debugging that in production.
 *
 * Runs only from vercel.json's buildCommand, so local `npm run build`, the
 * Playwright suite and CI are unaffected (they proxy /api via vite instead).
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PLACEHOLDER = 'REPLACE-ME.example.com';

const here = dirname(fileURLToPath(import.meta.url));
const configPath = join(here, '..', 'vercel.json');
const config = JSON.parse(readFileSync(configPath, 'utf8'));

const offenders = (config.rewrites ?? []).filter((r) =>
  String(r.destination).includes(PLACEHOLDER),
);

if (offenders.length > 0) {
  console.error(
    `\n✗ vercel.json still points at the placeholder backend (${PLACEHOLDER}).\n\n` +
      offenders.map((r) => `    ${r.source}  ->  ${r.destination}`).join('\n') +
      `\n\n  Set your backend origin, then redeploy:\n\n` +
      `    cd frontend\n` +
      `    sed -i '' 's|https://${PLACEHOLDER}|https://YOUR-BACKEND-URL|g' vercel.json\n\n` +
      `  See docs/VERCEL_DEPLOY.md. The backend must be a container host —\n` +
      `  it cannot run on Vercel (2.23 GB image, persistent disk, MJPEG streams).\n`,
  );
  process.exit(1);
}

console.log('✓ Backend rewrite target configured — proceeding with build.');
