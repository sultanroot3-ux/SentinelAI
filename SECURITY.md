# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅        |
| < 1.0   | ❌        |

## Reporting a vulnerability

**Please do not open public issues for security vulnerabilities.**

Report privately via one of:

1. **GitHub private vulnerability reporting** (preferred):
   [Security → Report a vulnerability](https://github.com/sultanroot3-ux/SentinelAI/security/advisories/new)
2. **Email**: sultanroot3@gmail.com — include "SECURITY" in the subject

Please include: affected component/endpoint, reproduction steps or PoC,
impact assessment, and suggested fix if you have one. You can expect an
acknowledgement within 7 days. Coordinated disclosure is appreciated — please
allow a fix to land before publishing details.

## Scope notes

SentinelAI processes **biometric data** (face embeddings, snapshots), so the
following classes of issues are treated as high severity:

- Authentication/authorization bypass (JWT, refresh rotation, RBAC)
- Unmasked secret exposure (SMTP/Telegram/Discord credentials, tokens)
- Access to face embeddings, user photos, or unknown-visitor snapshots
  without proper authorization
- SQL injection or path traversal in any endpoint
- Bypass of the liveness/anti-spoofing checks *by remote input alone*
  (physical presentation attacks — printed photos, replays — are a known,
  documented limitation of the heuristic and not a reportable vulnerability)

## Deployment hardening

Operators should follow the production checklist in
`deployment/DEPLOYMENT.md`: production env validation, unique secrets, TLS,
rate limiting (built in), backups, and network isolation of the dashboard.
