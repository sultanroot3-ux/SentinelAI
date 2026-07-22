"""Integration tests: unknown-visitor -> investigation case workflow."""
from app.models.models import UnknownFace


def _seed_unknown(db) -> int:
    row = UnknownFace(snapshot_url="/static/unknown_faces/x.jpg", camera="testcam")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def test_full_case_lifecycle(client, admin_headers, db_session):
    unknown_id = _seed_unknown(db_session)

    resp = client.post(
        "/api/cases",
        headers=admin_headers,
        json={
            "unknown_face_id": unknown_id,
            "priority": "high",
            "notes": "Investigate",
            "assigned_to": 1,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    case = resp.json()
    assert case["case_number"].startswith("CASE-")
    assert case["status"] == "open"
    # snapshot is now returned as a signed media URL, never the raw static path
    assert case["snapshot_url"].startswith("/api/media/unknown_faces/x.jpg?")
    assert "/static/" not in case["snapshot_url"]

    cid = case["id"]
    resp = client.put(
        f"/api/cases/{cid}",
        headers=admin_headers,
        json={"status": "investigating", "priority": "critical"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "investigating"

    resp = client.put(
        f"/api/cases/{cid}",
        headers=admin_headers,
        json={"status": "closed", "resolution": "False alarm"},
    )
    assert resp.status_code == 200
    assert resp.json()["resolution"] == "False alarm"


def test_case_for_missing_unknown_face(client, admin_headers):
    resp = client.post(
        "/api/cases",
        headers=admin_headers,
        json={"unknown_face_id": 999999, "priority": "low"},
    )
    assert resp.status_code == 404


def test_unknown_status_update_and_filter(client, admin_headers, db_session):
    unknown_id = _seed_unknown(db_session)
    resp = client.put(
        f"/api/unknown/{unknown_id}", headers=admin_headers, json={"status": "reviewed"}
    )
    assert resp.status_code == 200
    resp = client.get(
        "/api/unknown", headers=admin_headers, params={"status": "reviewed"}
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    assert any(i["id"] == unknown_id for i in items)
