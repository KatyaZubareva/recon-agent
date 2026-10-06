import os
import subprocess
import sys

import httpx
import pytest
from conftest import make_source, serving

from recon import agent_tools
from recon.importer import run_import


@pytest.fixture
def loaded(importer_dsn, dataset):
    source = make_source(serving(dataset))
    assert run_import(source, importer_dsn).status == "ok"
    return source


def test_pg_read_named_queries(loaded, reader_dsn):
    charges = agent_tools.pg_read(reader_dsn, "charges_by_period", period="2026-08")
    totals = agent_tools.pg_read(reader_dsn, "totals_by_period", period="2026-08")
    one = agent_tools.pg_read(reader_dsn, "charge_by_id", record_id="charge-3")

    assert [row["id"] for row in charges["rows"]] == ["charge-1", "charge-2", "charge-3"]
    assert totals["rows"] == [
        {"account_number": "10001", "charges": 2, "amount_kopecks": 150000},
        {"account_number": "20002", "charges": 1, "amount_kopecks": 990000},
        {"account_number": None, "charges": 3, "amount_kopecks": 1140000},
    ]
    assert type(totals["rows"][-1]["amount_kopecks"]) is int
    assert one["rows"] == [
        {
            "id": "charge-3",
            "account_id": "acc-bob",
            "account_number": "20002",
            "period": "2026-08",
            "amount_kopecks": 990000,
        }
    ]


@pytest.mark.parametrize(
    ("query", "params"),
    [
        ("DELETE FROM charges", {}),
        ("charges_by_period", {}),
        ("charges_by_period", {"period": "2026-08' OR '1'='1"}),
        ("recon_discrepancies", {"run_id": "1; DROP TABLE charges"}),
    ],
)
def test_pg_read_rejects_unknown_queries_and_bad_params(loaded, reader_dsn, query, params):
    with pytest.raises(ValueError):
        agent_tools.pg_read(reader_dsn, query, **params)


def test_onec_read_filters_by_period(loaded):
    result = agent_tools.onec_read(loaded, "charges", "2026-09")
    assert result["status"] == "ok"
    assert [row["id"] for row in result["rows"]] == ["charge-4"]


def test_onec_read_reports_source_error():
    result = agent_tools.onec_read(make_source(lambda r: httpx.Response(500)), "charges")
    assert result["status"] == "error"


def test_validate_source_reports_new_rule(dataset):
    dataset["payments"][0]["account_id"] = None
    result = agent_tools.validate_source(make_source(serving(dataset)))

    assert result["status"] == "problems"
    assert "required_account_id" in result["rules"]
    assert [(p["rule"], p["record_id"]) for p in result["problems"]] == [
        ("required_account_id", "payment-1")
    ]


def test_agent_reconcile_writes_report_file(
    loaded, importer_dsn, reader_dsn, tmp_path, monkeypatch
):
    monkeypatch.setattr(agent_tools, "REPORTS_DIR", tmp_path / "artifacts" / "reports")
    result = agent_tools.reconcile(loaded, reader_dsn, "2026-08")

    assert result["status"] == "ok"
    assert (tmp_path / result["report_file"]).exists()


def test_mcp_server_refuses_write_credentials():
    env = {**os.environ, "RECON_IMPORTER_DSN": "postgresql://importer:x@localhost/reporting"}
    proc = subprocess.run(
        [sys.executable, "-m", "recon.mcp_server"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode != 0
    assert "ключи записи" in proc.stderr
