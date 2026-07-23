# SentinelAI — Data Retention & Biometric Data Policy

This document describes how SentinelAI stores and deletes biometric data, and
how administrators configure retention. It supports compliance with biometric
privacy regimes (GDPR Art. 9, BIPA-style laws) that require a defined
retention period and automatic deletion of biometric identifiers.

## What biometric data SentinelAI stores

| Data | Where | Basis |
|---|---|---|
| Employee face embedding (512-d) | `users.face_embedding` + `face_embeddings` | consent — enrollment by an administrator |
| Employee profile photo | media volume `uploads/` | enrollment |
| Unknown-person snapshot | media volume `unknown_faces/` | security monitoring |
| Unknown-person embedding | `face_embeddings` | security monitoring |

No CNIC/national-ID/passport/address/GPS is ever stored or derived — see the
Investigation System data policy.

## Employee data

Employee biometric data is deleted when the employee account is deleted:
`face_embeddings` rows cascade, and the deletion is written to the audit log.
Re-enrolling (uploading a new photo) replaces the stored embedding.

## Unknown-person data — automatic retention

Unknown-person records are governed by the **`unknown_retention_days`**
setting (Settings → Data Retention, or `PUT /api/settings`).

- **Default: `0` = retention disabled** (records kept indefinitely). Set a
  positive number of days to enable automatic purging.
- A background purge runs at startup and every 6 hours. It deletes every
  unknown-person record whose `timestamp` is older than the window —
  **snapshot image, stored embedding, and the database row together**.
- **Protected from purging, regardless of age:**
  - records linked to an investigation **case** (evidence), and
  - records on any **watchlist**.
- Every purge that deletes at least one record writes a **`retention_purge`
  audit entry** listing the purged identifiers, so deletion is accountable.

`access_history` rows referencing a purged unknown keep their history with the
`unknown_face_id` set to NULL (the event happened; the biometric identifier is
gone).

## Recommended settings

| Context | Suggested value |
|---|---|
| Standard office security | 30–90 days |
| Strict privacy jurisdiction | shortest that meets operational need (e.g. 7–30) |
| Active investigation site | protect evidence via cases/watchlists; keep window modest |

## Verifying deletion

- **Audit log** (Audit Log page, or `GET /api/audit?action=retention_purge`)
  lists every purge with counts and identifiers.
- The snapshot files are removed from the media volume; the embeddings are
  removed from `face_embeddings`. A DB dump after a purge will not contain the
  purged rows.

## Backups and the right to erasure

Purging removes data from the live system. Backups (`./backups`, offsite
targets) are point-in-time copies and will still contain purged records until
they age out of the backup retention window (`BACKUP_RETENTION_DAYS`, default
14 days). For a hard erasure guarantee, keep the backup retention window no
longer than your policy allows, or document backups as a separate controlled
store in your data-processing records.
