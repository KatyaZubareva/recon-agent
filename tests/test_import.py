import httpx
import psycopg
import pytest
from conftest import FIXTURES, make_source, query, serving

from recon.importer import run_import

TOTALS_SQL = "SELECT count(*), sum(amount_kopecks) FROM charges WHERE period = %s"


def snapshot(dsn: str) -> dict:
    return {
        "accounts": query(dsn, "SELECT id, account_number FROM accounts ORDER BY id"),
        "charges": query(
            dsn, "SELECT id, account_id, period, amount_kopecks FROM charges ORDER BY id"
        ),
        "payments": query(
            dsn, "SELECT id, account_id, date::text, amount_kopecks FROM payments ORDER BY id"
        ),
    }


def test_first_and_repeated_import_keep_ids_links_and_totals(importer_dsn, dataset):
    source = make_source(serving(dataset))

    first = run_import(source, importer_dsn)
    after_first = snapshot(importer_dsn)
    second = run_import(source, importer_dsn)

    assert first.status == second.status == "ok"
    assert first.counts == second.counts == {"accounts": 2, "charges": 4, "payments": 1}
    assert snapshot(importer_dsn) == after_first  # повтор ничего не меняет и не дублирует
    assert after_first["charges"] == [
        (r["id"], r["account_id"], r["period"], r["amount_kopecks"]) for r in FIXTURES["charges"]
    ]
    assert after_first["payments"] == [("payment-1", "acc-alice", "2026-08-20", 100000)]
    assert query(importer_dsn, TOTALS_SQL, ("2026-08",)) == [(3, 1140000)]
    assert query(importer_dsn, TOTALS_SQL, ("2026-09",)) == [(1, 5000)]
    assert query(importer_dsn, "SELECT status FROM import_runs") == [("ok",), ("ok",)]


def test_repeated_import_restores_rows_changed_in_postgres(importer_dsn, dataset):
    source = make_source(serving(dataset))
    run_import(source, importer_dsn)
    expected = snapshot(importer_dsn)
    with psycopg.connect(importer_dsn) as conn:
        conn.execute("DELETE FROM charges WHERE id = 'charge-2'")
        conn.execute("UPDATE charges SET amount_kopecks = 1 WHERE id = 'charge-3'")

    assert run_import(source, importer_dsn).status == "ok"
    assert snapshot(importer_dsn) == expected


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(500), id="http-500"),
        pytest.param(
            lambda r: (
                httpx.Response(500)
                if "charges" in r.url.path
                else httpx.Response(200, json={"value": []})
            ),
            id="charges-500",
        ),
        pytest.param(lambda r: httpx.Response(200, json={"items": []}), id="no-value"),
        pytest.param(lambda r: httpx.Response(200, text="<html>"), id="not-json"),
    ],
)
def test_source_failure_is_error_not_empty_import(importer_dsn, handler):
    result = run_import(make_source(handler), importer_dsn)

    assert result.status == "error"
    assert result.error.startswith("Источник:")
    assert result.counts == {}
    assert snapshot(importer_dsn) == {"accounts": [], "charges": [], "payments": []}
    assert query(importer_dsn, "SELECT status, error FROM import_runs") == [("error", result.error)]


def test_unreachable_source_is_error(importer_dsn):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    result = run_import(make_source(refuse), importer_dsn)
    assert result.status == "error"
    assert "ConnectError" in result.error


def test_source_failure_keeps_previous_data(importer_dsn, dataset):
    run_import(make_source(serving(dataset)), importer_dsn)
    before = snapshot(importer_dsn)

    assert run_import(make_source(lambda r: httpx.Response(503)), importer_dsn).status == "error"
    assert snapshot(importer_dsn) == before


@pytest.mark.parametrize(
    ("mutate", "rule", "record_id"),
    [
        (lambda d: d["charges"][0].update(amount_kopecks=1250.5), "integer_amounts", "charge-1"),
        (lambda d: d["charges"][0].update(amount_kopecks="125050"), "integer_amounts", "charge-1"),
        (lambda d: d["charges"][1].update(period="2026-8"), "period_format", "charge-2"),
        (lambda d: d["payments"][0].update(date="20.08.2026"), "date_format", "payment-1"),
        (
            lambda d: d["charges"][2].update(account_id="acc-nobody"),
            "account_reference",
            "charge-3",
        ),
        (lambda d: d["charges"].append(dict(d["charges"][0])), "unique_ids", "charge-1"),
    ],
)
def test_invalid_data_is_rejected_before_import(importer_dsn, dataset, mutate, rule, record_id):
    mutate(dataset)
    result = run_import(make_source(serving(dataset)), importer_dsn)

    assert result.status == "rejected"
    assert {(p["rule"], p["record_id"]) for p in result.problems} == {(rule, record_id)}
    assert snapshot(importer_dsn) == {"accounts": [], "charges": [], "payments": []}


def test_agent_reader_can_read_but_not_write(importer_dsn, reader_dsn, dataset):
    run_import(make_source(serving(dataset)), importer_dsn)

    assert query(reader_dsn, "SELECT count(*) FROM charges") == [(4,)]
    with psycopg.connect(reader_dsn) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM charges")
    # Даже если снять read-only в сеансе, у роли нет прав на запись.
    with psycopg.connect(reader_dsn) as conn:
        conn.execute("SET default_transaction_read_only = off")
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE charges SET amount_kopecks = 0")


def test_import_into_empty_database_creates_schema(dataset):
    # Воспроизводимость: импорт по README на свежей PG, до первого старта приложения.
    from conftest import ADMIN_DSN, _dsn

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS reporting_empty WITH (FORCE)")
        conn.execute("CREATE DATABASE reporting_empty")
    dsn = _dsn("reporting_empty")
    try:
        result = run_import(make_source(serving(dataset)), dsn)
        assert result.status == "ok"
        assert query(dsn, "SELECT status FROM import_runs") == [("ok",)]
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS reporting_empty WITH (FORCE)")


def test_unreachable_database_is_error_not_traceback(dataset):
    bad = "postgresql://importer:wrong@localhost:5543/reporting_test"
    result = run_import(make_source(serving(dataset)), bad)
    assert result.status == "error"
    assert result.error.startswith("PostgreSQL:")
