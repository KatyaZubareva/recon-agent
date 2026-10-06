from fastapi.testclient import TestClient

from source.app import app

client = TestClient(app)


def test_source_is_read_only():
    assert client.post("/charges", json={}).status_code == 405


def test_fixed_fixture():
    rows = client.get("/charges").json()["value"]
    assert sum(row["amount_kopecks"] for row in rows if row["period"] == "2026-08") == 1140000
    assert len({row["id"] for row in rows}) == len(rows)
