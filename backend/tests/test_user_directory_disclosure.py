"""GET /api/users must not disclose who is still on a default password.

Found during the pre-publication verification pass: `GET /api/users` is
guarded by `get_current_user` only — deliberately, because a receptionist needs
the employee directory to register visitors against a host — but it was
serializing `must_change_password` for every row. Any authenticated account,
including the lowest-privileged one, could therefore read off exactly which
admin accounts were still on a seeded or freshly-reset password.

That is a target list handed to the least-trusted tier of access. The flag is
only ever acted on for the *current* user (frontend `AuthContext`), so blanking
it for everyone else changes no behaviour.
"""


def _find(rows, username):
    return next((r for r in rows if r["username"] == username), None)


def test_directory_hides_other_users_password_state(client, admin_headers):
    """An admin listing users sees the flag on their own row, not on others."""
    # The seeded default admin is created with must_change_password=True.
    resp = client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()

    me = client.get("/api/auth/me", headers=admin_headers).json()
    for row in rows:
        if row["id"] == me["id"]:
            continue
        assert row["must_change_password"] is False, (
            f"user {row['username']!r} leaked must_change_password in the "
            "directory listing"
        )


def test_receptionist_cannot_see_any_password_state(client, receptionist_headers):
    """The lowest-privileged role learns nothing about other accounts."""
    resp = client.get("/api/users", headers=receptionist_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "expected the directory to be readable by a receptionist"

    me = client.get("/api/auth/me", headers=receptionist_headers).json()
    leaked = [
        r["username"]
        for r in rows
        if r["id"] != me["id"] and r["must_change_password"]
    ]
    assert not leaked, f"password state leaked for: {leaked}"


def test_seeded_admin_password_state_is_not_visible_to_a_receptionist(
    client, receptionist_headers
):
    """The specific attack this closes: locate the account still on admin123.

    Non-vacuous by construction — the seeded `admin` really is created with
    must_change_password=True (app/main.py), so before the fix this row
    reported True and named the target directly.
    """
    rows = client.get("/api/users", headers=receptionist_headers).json()
    seeded = _find(rows, "admin")
    assert seeded is not None, "seeded admin should appear in the directory"
    assert seeded["must_change_password"] is False


def test_current_user_still_sees_their_own_flag(client, admin_headers):
    """The forced-password-change flow must keep working.

    `/api/auth/me` is what AuthContext reads, so it must still report the real
    value even though the directory does not.
    """
    me = client.get("/api/auth/me", headers=admin_headers)
    assert me.status_code == 200
    assert "must_change_password" in me.json()
