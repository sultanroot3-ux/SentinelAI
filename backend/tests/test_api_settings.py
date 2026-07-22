"""Integration tests: settings API — validation, secret masking, round-trips."""


def test_get_settings_masks_secrets(client, admin_headers):
    client.put(
        "/api/settings",
        headers=admin_headers,
        json={"telegram_bot_token": "real-secret-token"},
    )
    resp = client.get("/api/settings", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["telegram_bot_token"] == "********"


def test_mask_roundtrip_does_not_clobber_secret(client, admin_headers, db_session):
    from app.services.settings_service import get_setting

    client.put(
        "/api/settings",
        headers=admin_headers,
        json={"smtp_password": "the-real-password"},
    )
    # UI sends the mask back — stored secret must survive
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"smtp_password": "********"}
    )
    assert resp.status_code == 200
    assert get_setting(db_session, "smtp_password") == "the-real-password"


def test_unknown_key_rejected(client, admin_headers):
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"not_a_real_key": 1}
    )
    assert resp.status_code == 422


def test_threshold_validation(client, admin_headers):
    for bad in (-0.1, 1.5, "high", True):
        resp = client.put(
            "/api/settings",
            headers=admin_headers,
            json={"recognition_threshold": bad},
        )
        assert resp.status_code == 422, f"accepted bad threshold {bad!r}"
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"recognition_threshold": 0.45}
    )
    assert resp.status_code == 200


def test_bool_validation(client, admin_headers):
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"email_enabled": "yes"}
    )
    assert resp.status_code == 422


def test_smtp_port_coercion(client, admin_headers):
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"smtp_port": "2525"}
    )
    assert resp.status_code == 200
    assert resp.json()["smtp_port"] == 2525
    client.put("/api/settings", headers=admin_headers, json={"smtp_port": 587})
