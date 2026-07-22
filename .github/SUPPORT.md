# Getting Help with SentinelAI

## 💬 Questions & community — GitHub Discussions

For anything that isn't a bug report or feature request, use
[GitHub Discussions](https://github.com/sultanroot3-ux/SentinelAI/discussions):

| Category | Use it for |
|---|---|
| **Q&A** | "How do I…" questions — setup, cameras, recognition tuning |
| **Ideas** | Early-stage feature ideas before they become formal requests |
| **Show and tell** | Your deployments, dashboards, integrations |
| **General** | Everything else |

Before asking, please check:
- [README](../README.md) — quick start and feature overview
- [docs/INSTALL.md](../docs/INSTALL.md) — installation, PostgreSQL, camera permissions (macOS notes!)
- [docs/TESTING.md](../docs/TESTING.md) — how to verify each subsystem
- [deployment/DEPLOYMENT.md](../deployment/DEPLOYMENT.md) — production, HTTPS, backups

## 🐛 Bugs → [Issues](https://github.com/sultanroot3-ux/SentinelAI/issues/new/choose)

Use the bug-report template and include logs (`logs/sentinel.log`) with
secrets redacted.

## 🔒 Security → [Private reporting](https://github.com/sultanroot3-ux/SentinelAI/security/advisories/new)

Never post vulnerabilities publicly — see [SECURITY.md](../SECURITY.md).

## Common gotchas (fast answers)

- **Camera dead on macOS** → start the backend with `python run.py` (not the
  bare `uvicorn` command) and grant camera permission to your terminal.
- **No recognition, detection only** → install the optional AI extras:
  `pip install insightface onnxruntime`.
- **`curl localhost` fails but the server runs** → use `127.0.0.1` (IPv6
  resolution quirk).
- **First login demands a password change** → intentional; the seeded
  `admin/admin123` account must be rotated.
