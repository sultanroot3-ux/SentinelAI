# SentinelAI — User Manual (v1.0)

Audience: everyday users — receptionists, security staff, and employees using
the dashboard. Administrators: see `docs/ADMIN_MANUAL.md`.

## Signing in

Open `https://<your-company-domain>/` and sign in with the username and
password your administrator gave you. If prompted, set a new password (at
least 8 characters). Use the sun/moon button (top right) to switch between
dark and light themes. The dashboard works on phones and tablets too.

What you see in the sidebar depends on your role — receptionists won't see
admin pages like Watchlists or the Audit Log.

## Dashboard

Your at-a-glance view: today's visitor counts, unknown sightings, open cases,
and the latest recognition activity.

## Live Camera

- The **Live Feed** shows the camera in real time.
- **AI Overlay On** draws live recognition boxes: **green** = recognized
  employee (name + confidence), **red** = unknown person, **amber** =
  liveness check in progress.
- **Reconnect** restarts the stream if it drops.
- **Snapshot Test**: upload any photo and press *Analyze Frame* to run
  recognition on it — useful for checking whether a photo would be
  recognized before enrolling it.

## Visitors (front desk)

1. **Register Visitor** — name, company, purpose, host employee, badge.
2. When they arrive: press the **✓ check-in** action and confirm.
3. When they leave: press **check-out**. Times are recorded automatically
   and appear in Access History.
4. Use the search box or status filter (Expected / Checked in / Checked out)
   to find a visitor quickly.

## Visitor Logs

Every recognition event: who was seen, on which camera, when, and with what
confidence. Filter by date range; pages of 25.

## Unknown Visitors

People the cameras saw but could not identify. Each card shows the snapshot,
camera, and time. Depending on your role you can mark them **Reviewed**,
**Investigate** them, or **Open Case** for follow-up.

## Cases

Investigation follow-ups with priority, assignee, notes, and resolution.
Click a row for details; update status as the investigation progresses.

## Access History

A timeline of everything the system recorded: detections, visitor check-ins
and check-outs — filterable by event type and employee.

## Notifications

The bell icon shows unread alerts (e.g. "Unknown person detected"). Open the
Notifications page to read or clear them.

## Profile

Change your own password here. If your face is enrolled, your profile photo
is shown; ask an administrator to update it.

## Good to know

- **Your face data**: enrolling stores a mathematical face signature (an
  embedding), used only to recognize you on company cameras. Administrators
  can remove it by deleting/re-uploading your photo.
- **Estimates are estimates**: AI-derived values shown in reports (age,
  gender, quality) are clearly labelled estimates — never treated as facts.
- If the Live Feed says **Camera Offline**, tell your administrator — it's
  almost always a camera-permission or cabling issue, not something you did.
