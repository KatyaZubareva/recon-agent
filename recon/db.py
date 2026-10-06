"""Подключение к отчётной PostgreSQL и применение схемы."""

from pathlib import Path

import psycopg

SCHEMA = Path(__file__).parent.parent / "db" / "schema.sql"


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)


def apply_schema(dsn: str) -> None:
    """Идемпотентно создаёт таблицы. Выполнять от importer."""
    with connect(dsn) as conn:
        conn.execute(SCHEMA.read_text())
