import httpx
import psycopg
import pytest
from conftest import make_source, serving
from fastapi.testclient import TestClient

from recon.api import create_app


@pytest.fixture
def client_for(importer_dsn, reader_dsn):
    """Фабрика клиента API с подменённым источником (handler MockTransport)."""

    def build(handler) -> TestClient:
        app = create_app(
            source_factory=lambda: make_source(handler),
            importer_dsn=lambda: importer_dsn,
            reader_dsn=lambda: reader_dsn,
        )
        return TestClient(app)

    return build


def run(client: TestClient, path: str, **kwargs) -> dict:
    """Запустить действие и дождаться результата (TestClient выполняет фон синхронно)."""
    started = client.post(path, **kwargs)
    assert started.status_code == 202, started.text
    job = client.get(f"/api/jobs/{started.json()['job_id']}").json()
    assert job["status"] == "finished"
    return job["result"]


def test_import_then_reconcile_are_separate_actions(client_for, dataset, importer_dsn):
    client = client_for(serving(dataset))

    imported = run(client, "/api/import")
    assert imported["status"] == "ok"
    assert imported["counts"] == {"accounts": 2, "charges": 4, "payments": 1}

    with psycopg.connect(importer_dsn) as conn:
        conn.execute("DELETE FROM charges WHERE id = 'charge-2'")
        conn.execute("UPDATE charges SET amount_kopecks = 999000 WHERE id = 'charge-3'")

    # Сверка не запускает импорт: внесённые расхождения не затираются.
    report = run(client, "/api/reconcile", json={"period": "2026-08"})
    assert report["status"] == "discrepancies"
    assert {(d["type"], d["record_id"]) for d in report["discrepancies"]} == {
        ("missing_in_target", "charge-2"),
        ("amount_mismatch", "charge-3"),
        ("totals_mismatch", None),
    }
    with psycopg.connect(importer_dsn) as conn:
        saved = conn.execute(
            "SELECT status FROM recon_runs WHERE id = %s", (report["run_id"],)
        ).fetchone()
    assert saved == ("discrepancies",)


def test_reconcile_ok_reports_period_and_totals(client_for, dataset):
    client = client_for(serving(dataset))
    run(client, "/api/import")

    report = run(client, "/api/reconcile", json={"period": "2026-08"})

    assert report["status"] == "ok"
    assert report["period"] == "2026-08"
    assert report["source"]["amount_kopecks"] == report["target"]["amount_kopecks"] == 1140000
    assert report["discrepancies"] == []


def test_source_down_is_visible_error(client_for, dataset):
    run(client_for(serving(dataset)), "/api/import")
    down = client_for(lambda r: httpx.Response(503))

    imported = run(down, "/api/import")
    report = run(down, "/api/reconcile", json={"period": "2026-08"})

    assert imported["status"] == "error" and "503" in imported["error"]
    assert report["status"] == "error" and "503" in report["error"]
    assert report["source"] is None


def test_bad_period_and_unknown_job(client_for, dataset):
    client = client_for(serving(dataset))
    assert client.post("/api/reconcile", json={"period": "08.2026"}).status_code == 422
    assert client.get("/api/jobs/nope").status_code == 404
