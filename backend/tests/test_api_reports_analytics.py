"""Integration tests: reports in all 4 formats + analytics endpoints."""
from app.models.models import RecognitionLog


def _seed_log(db):
    db.add(RecognitionLog(user_id=1, camera="testcam", score=0.91))
    db.commit()


def test_report_json(client, admin_headers, db_session):
    _seed_log(db_session)
    resp = client.get(
        "/api/reports/visitors",
        headers=admin_headers,
        params={"period": "daily", "format": "json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "daily"
    assert body["total"] >= 1
    assert body["items"][0]["camera"]


def test_report_csv(client, admin_headers):
    resp = client.get(
        "/api/reports/visitors",
        headers=admin_headers,
        params={"period": "weekly", "format": "csv"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("id,user_id,user_name")
    assert len(lines) >= 2


def test_report_pdf(client, admin_headers):
    resp = client.get(
        "/api/reports/visitors",
        headers=admin_headers,
        params={"period": "monthly", "format": "pdf"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_report_xlsx(client, admin_headers):
    resp = client.get(
        "/api/reports/visitors",
        headers=admin_headers,
        params={"period": "monthly", "format": "xlsx"},
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"  # zip container magic


def test_report_bad_format_rejected(client, admin_headers):
    resp = client.get(
        "/api/reports/visitors",
        headers=admin_headers,
        params={"period": "daily", "format": "docx"},
    )
    assert resp.status_code == 422


def test_analytics_summary_shape(client, admin_headers):
    resp = client.get("/api/analytics/summary", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total_users", "today_visitors", "today_unknown", "open_cases"):
        assert key in body


def test_analytics_daily_counts_today(client, admin_headers, db_session):
    _seed_log(db_session)
    resp = client.get(
        "/api/analytics/daily", headers=admin_headers, params={"days": 2}
    )
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 2
    assert points[-1]["recognized"] >= 1  # today's UTC bucket includes the seed


def test_analytics_peak_hours_full_day(client, admin_headers):
    resp = client.get("/api/analytics/peak-hours", headers=admin_headers)
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 24
    assert sum(p["count"] for p in points) >= 1


def test_analytics_cameras(client, admin_headers):
    resp = client.get("/api/analytics/cameras", headers=admin_headers)
    assert resp.status_code == 200
    assert any(p["camera"] == "testcam" for p in resp.json())
