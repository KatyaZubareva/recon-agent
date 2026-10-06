import httpx
import psycopg
import pytest
from conftest import make_source, query, serving

from recon.importer import run_import
from recon.reconcile import run_reconciliation, save_report_db, save_report_file


@pytest.fixture
def loaded(importer_dsn, dataset):
    """PG заполнена импортом из источника с данными fixtures/data.json."""
    source = make_source(serving(dataset))
    assert run_import(source, importer_dsn).status == "ok"
    return source


def pg(dsn: str, sql: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(sql)


def kinds(report) -> set[tuple]:
    return {(d["type"], d["record_id"]) for d in report.discrepancies}


def test_same_data_reports_no_discrepancies_with_totals(loaded, reader_dsn):
    report = run_reconciliation("2026-08", loaded, reader_dsn)

    assert report.status == "ok"
    assert report.period == "2026-08"
    assert report.discrepancies == []
    assert report.source["count"] == report.target["count"] == 3
    assert report.source["amount_kopecks"] == report.target["amount_kopecks"] == 1140000
    assert "totals_mismatch" in report.rules


def test_deleted_and_changed_charge_are_found_with_ids(loaded, importer_dsn, reader_dsn):
    pg(importer_dsn, "DELETE FROM charges WHERE id = 'charge-2'")
    pg(importer_dsn, "UPDATE charges SET amount_kopecks = 999000 WHERE id = 'charge-3'")

    report = run_reconciliation("2026-08", loaded, reader_dsn)

    assert report.status == "discrepancies"
    assert kinds(report) == {
        ("missing_in_target", "charge-2"),
        ("amount_mismatch", "charge-3"),
        ("totals_mismatch", None),
    }
    by_id = {d["record_id"]: d for d in report.discrepancies}
    assert by_id["charge-2"]["source"]["amount_kopecks"] == 24950
    assert by_id["charge-2"]["target"] is None
    assert by_id["charge-3"]["source"]["amount_kopecks"] == 990000
    assert by_id["charge-3"]["target"]["amount_kopecks"] == 999000
    assert report.source == {**report.source, "count": 3, "amount_kopecks": 1140000}
    assert report.target == {**report.target, "count": 2, "amount_kopecks": 1124050}


def test_repeated_import_removes_discrepancies(loaded, importer_dsn, reader_dsn):
    pg(importer_dsn, "DELETE FROM charges WHERE id = 'charge-2'")
    assert run_reconciliation("2026-08", loaded, reader_dsn).status == "discrepancies"

    assert run_import(loaded, importer_dsn).status == "ok"
    assert run_reconciliation("2026-08", loaded, reader_dsn).status == "ok"


def test_period_boundary(loaded, importer_dsn, reader_dsn):
    # Сентябрьское начисление не влияет на август, но ловится сверкой сентября.
    pg(importer_dsn, "UPDATE charges SET amount_kopecks = 1 WHERE id = 'charge-4'")

    august = run_reconciliation("2026-08", loaded, reader_dsn)
    september = run_reconciliation("2026-09", loaded, reader_dsn)

    assert august.status == "ok"
    assert august.source["count"] == 3
    assert kinds(september) == {("amount_mismatch", "charge-4"), ("totals_mismatch", None)}


def test_extra_row_in_postgres_and_changed_account(loaded, importer_dsn, reader_dsn):
    pg(importer_dsn, """INSERT INTO charges VALUES ('charge-x', 'acc-bob', '2026-08', 100)""")
    pg(importer_dsn, "UPDATE charges SET account_id = 'acc-bob' WHERE id = 'charge-1'")

    report = run_reconciliation("2026-08", loaded, reader_dsn)

    assert kinds(report) == {
        ("missing_in_source", "charge-x"),
        ("account_mismatch", "charge-1"),
        ("totals_mismatch", None),
    }


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(500), id="http-500"),
        pytest.param(lambda r: httpx.Response(401), id="unauthorized"),
        pytest.param(lambda r: httpx.Response(200, json={}), id="no-value"),
    ],
)
def test_source_failure_is_error_not_ok(loaded, reader_dsn, handler):
    report = run_reconciliation("2026-08", make_source(handler), reader_dsn)

    assert report.status == "error"
    assert report.error.startswith("Источник 1С:")
    assert report.source is None and report.target is None
    assert report.discrepancies == []


def test_unreachable_source_is_error(loaded, reader_dsn):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    report = run_reconciliation("2026-08", make_source(refuse), reader_dsn)
    assert report.status == "error"
    assert "ConnectError" in report.error


def test_source_breaking_contract_is_error(importer_dsn, reader_dsn, dataset):
    run_import(make_source(serving(dataset)), importer_dsn)
    dataset["charges"][0]["amount_kopecks"] = 1250.5

    report = run_reconciliation("2026-08", make_source(serving(dataset)), reader_dsn)
    assert report.status == "error"
    assert "charge-1" in report.error


def test_postgres_failure_is_error(loaded):
    bad_dsn = "postgresql://agent_reader:wrong@localhost:5543/reporting_test"
    report = run_reconciliation("2026-08", loaded, bad_dsn)
    assert report.status == "error"
    assert report.error.startswith("PostgreSQL:")


def test_invalid_period_is_rejected(loaded, reader_dsn):
    with pytest.raises(ValueError):
        run_reconciliation("2026-8", loaded, reader_dsn)


def test_report_is_saved_to_db_and_file(loaded, importer_dsn, reader_dsn, tmp_path):
    pg(importer_dsn, "DELETE FROM charges WHERE id = 'charge-2'")
    report = run_reconciliation("2026-08", loaded, reader_dsn)

    save_report_db(report, importer_dsn)
    path = save_report_file(report, tmp_path)

    assert query(
        reader_dsn,
        "SELECT period, status, source_count, source_amount_kopecks, target_count,"
        " target_amount_kopecks FROM recon_runs WHERE id = %s",
        (report.run_id,),
    ) == [("2026-08", "discrepancies", 3, 1140000, 2, 1115050)]
    assert query(
        reader_dsn,
        "SELECT type, record_id FROM recon_discrepancies WHERE run_id = %s ORDER BY position",
        (report.run_id,),
    ) == [("missing_in_target", "charge-2"), ("totals_mismatch", None)]
    assert report.run_id in path.name and path.read_text().count("charge-2") >= 1
