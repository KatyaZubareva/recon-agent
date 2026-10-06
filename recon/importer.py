"""Импорт 1С → PostgreSQL.

Порядок: прочитать ВСЕ коллекции → проверить правилами → записать одной транзакцией.
- Ошибка источника → статус error, в таблицы данных ничего не пишется
  (ошибка не превращается в «успешную пустую выгрузку»).
- Нарушены правила → статус rejected со списком записей, данные не пишутся.
- Запись — upsert по id: повторный импорт не создаёт дублей и возвращает
  изменённые/удалённые в PG строки к состоянию источника.
Каждая попытка фиксируется в import_runs (отдельной транзакцией, чтобы ошибка
тоже осталась в журнале). Схема создаётся идемпотентно перед импортом — импорт
работает и на пустой БД, даже если приложение ещё не запускалось.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from recon.db import apply_schema, connect
from recon.rules import run_validation
from recon.source import Dataset, SourceClient, SourceError


@dataclass
class ImportResult:
    run_id: str
    status: str  # ok | rejected | error
    source: str
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def run_import(source: SourceClient, importer_dsn: str) -> ImportResult:
    result = ImportResult(run_id=str(uuid.uuid4()), status="running", source=source.base_url)
    try:
        apply_schema(importer_dsn)
        _journal_start(importer_dsn, result)
    except psycopg.Error as error:  # БД недоступна — даже журнал записать нельзя
        result.status, result.error = "error", f"PostgreSQL: {type(error).__name__}: {error}"
        return result
    try:
        dataset = source.fetch_all()
        problems = run_validation(dataset)
        if problems:
            result.status = "rejected"
            result.problems = [problem.as_dict() for problem in problems]
        else:
            _upsert(importer_dsn, dataset)
            result.status = "ok"
            result.counts = {name: len(rows) for name, rows in dataset.items()}
    except SourceError as error:
        result.status, result.error = "error", f"Источник: {error}"
    except psycopg.Error as error:
        result.status, result.error = "error", f"PostgreSQL: {type(error).__name__}: {error}"
    _journal_finish(importer_dsn, result)
    return result


def _upsert(dsn: str, data: Dataset) -> None:
    # Одна транзакция: либо все три коллекции, либо ничего.
    with connect(dsn) as conn, conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO accounts (id, account_number) VALUES (%(id)s, %(account_number)s)
               ON CONFLICT (id) DO UPDATE SET account_number = EXCLUDED.account_number""",
            data["accounts"],
        )
        cur.executemany(
            """INSERT INTO charges (id, account_id, period, amount_kopecks)
               VALUES (%(id)s, %(account_id)s, %(period)s, %(amount_kopecks)s)
               ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id,
                   period = EXCLUDED.period, amount_kopecks = EXCLUDED.amount_kopecks""",
            data["charges"],
        )
        cur.executemany(
            """INSERT INTO payments (id, account_id, date, amount_kopecks)
               VALUES (%(id)s, %(account_id)s, %(date)s, %(amount_kopecks)s)
               ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id,
                   date = EXCLUDED.date, amount_kopecks = EXCLUDED.amount_kopecks""",
            data["payments"],
        )


def _journal_start(dsn: str, result: ImportResult) -> None:
    with connect(dsn) as conn:
        conn.execute(
            "INSERT INTO import_runs (id, status, source) VALUES (%s, 'running', %s)",
            (result.run_id, result.source),
        )


def _journal_finish(dsn: str, result: ImportResult) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """UPDATE import_runs SET finished_at = now(), status = %s, counts = %s,
                   problems = %s, error = %s WHERE id = %s""",
            (
                result.status,
                Jsonb(result.counts) if result.counts else None,
                Jsonb(result.problems) if result.problems else None,
                result.error,
                result.run_id,
            ),
        )
