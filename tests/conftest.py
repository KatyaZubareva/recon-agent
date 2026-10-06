"""Общие фикстуры: отдельная тестовая БД и подменный HTTP-источник.

Тесты используют PostgreSQL из compose.yaml (docker compose up -d --wait postgres),
но работают в отдельной базе reporting_test, рабочую reporting не трогают.
Источник в автотестах — httpx.MockTransport (по условию моки допустимы в автотестах;
интеграция с настоящей 1С подтверждается отдельно, см. README).
"""

import copy
import json
import os
from pathlib import Path

import httpx
import psycopg
import pytest

from recon.config import SourceSettings
from recon.db import apply_schema
from recon.source import SourceClient

FIXTURES = json.loads((Path(__file__).parent.parent / "fixtures/data.json").read_text())
ADMIN_DSN = os.environ.get(
    "RECON_IMPORTER_DSN", "postgresql://importer:demo-importer-local@localhost:5543/reporting"
)
TEST_DB = "reporting_test"


def _dsn(dbname: str, user: str = "importer", password: str = "demo-importer-local") -> str:
    info = psycopg.conninfo.conninfo_to_dict(ADMIN_DSN)
    info.update(dbname=dbname, user=user, password=password)
    return psycopg.conninfo.make_conninfo(**info)


@pytest.fixture(scope="session")
def _test_database():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    # Те же права, что postgres/init.sql выдаёт в рабочей базе.
    with psycopg.connect(_dsn(TEST_DB), autocommit=True) as conn:
        conn.execute(f"GRANT CONNECT ON DATABASE {TEST_DB} TO agent_reader")
        conn.execute("GRANT USAGE ON SCHEMA public TO agent_reader")
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE importer IN SCHEMA public "
            "GRANT SELECT ON TABLES TO agent_reader"
        )
    apply_schema(_dsn(TEST_DB))
    yield


@pytest.fixture
def importer_dsn(_test_database) -> str:
    """Чистые таблицы перед каждым тестом."""
    dsn = _dsn(TEST_DB)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "TRUNCATE accounts, charges, payments, import_runs, recon_runs, recon_discrepancies"
        )
    return dsn


@pytest.fixture
def reader_dsn(_test_database) -> str:
    return _dsn(TEST_DB, "agent_reader", "demo-reader-local")


@pytest.fixture
def dataset() -> dict:
    """Изменяемая копия fixtures/data.json для подмены источника."""
    return copy.deepcopy(FIXTURES)


def make_source(handler) -> SourceClient:
    settings = SourceSettings(
        base_url="http://source.test",
        user="",
        password="",
        paths={name: name for name in ("accounts", "charges", "payments")},
    )
    return SourceClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def serving(data: dict):
    """Обработчик MockTransport, отдающий data по контракту."""

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.strip("/")
        if name not in data:
            return httpx.Response(404)
        return httpx.Response(200, json={"value": data[name]})

    return handler


def query(dsn: str, sql: str, params=()) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).fetchall()
