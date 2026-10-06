"""Инструменты агента — только чтение. Используются MCP-сервером (recon/mcp_server.py).

Ограничения обеспечиваются не текстом промпта, а доступами:
- 1С: пользователь reader (роль ЧтениеДанных — чтение справочников и GET-методы);
- PostgreSQL: роль agent_reader (только SELECT, read-only транзакции) + сеанс read_only;
- SQL: только заранее заданные параметризованные запросы, произвольного SQL нет;
- пароль импортёра агенту не передаётся (RECON_IMPORTER_DSN в окружении запрещён).
"""

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from recon import config
from recon.reconcile import PERIOD_RE, run_reconciliation, save_report_file
from recon.rules import list_rules, run_validation
from recon.source import COLLECTIONS, SourceClient, SourceError

REPORTS_DIR = Path(__file__).parent.parent / "artifacts" / "reports"
FORBIDDEN_ENV = ("RECON_IMPORTER_DSN", "ONEC_ADMIN_USER", "ONEC_ADMIN_PASSWORD")

CHARGE_COLUMNS = "c.id, c.account_id, a.account_number, c.period, c.amount_kopecks"
# Имя запроса -> (SQL, обязательные параметры). Значения передаются только параметрами.
QUERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "accounts": ("SELECT id, account_number FROM accounts ORDER BY id", ()),
    "charges_by_period": (
        f"SELECT {CHARGE_COLUMNS} FROM charges c JOIN accounts a ON a.id = c.account_id"
        " WHERE c.period = %(period)s ORDER BY c.id",
        ("period",),
    ),
    "charge_by_id": (
        f"SELECT {CHARGE_COLUMNS} FROM charges c JOIN accounts a ON a.id = c.account_id"
        " WHERE c.id = %(record_id)s",
        ("record_id",),
    ),
    "totals_by_period": (
        "SELECT a.account_number, count(*) AS charges, sum(c.amount_kopecks) AS amount_kopecks"
        " FROM charges c JOIN accounts a ON a.id = c.account_id WHERE c.period = %(period)s"
        " GROUP BY ROLLUP (a.account_number) ORDER BY a.account_number NULLS LAST",
        ("period",),
    ),
    "payments": (
        "SELECT id, account_id, date, amount_kopecks FROM payments ORDER BY date, id",
        (),
    ),
    "import_runs": (
        "SELECT id, started_at, finished_at, status, counts, problems, error FROM import_runs"
        " ORDER BY started_at DESC LIMIT %(limit)s",
        ("limit",),
    ),
    "recon_runs": (
        "SELECT id, period, status, started_at, source_count, source_amount_kopecks,"
        " target_count, target_amount_kopecks, error FROM recon_runs"
        " ORDER BY started_at DESC LIMIT %(limit)s",
        ("limit",),
    ),
    "recon_discrepancies": (
        "SELECT position, type, record_id, source_value, target_value, message"
        " FROM recon_discrepancies WHERE run_id = %(run_id)s ORDER BY position",
        ("run_id",),
    ),
}


def ensure_read_only_environment(env: dict[str, str]) -> None:
    """Отказ запускаться, если агенту по ошибке передали ключи записи."""
    leaked = [name for name in FORBIDDEN_ENV if env.get(name)]
    if leaked:
        raise RuntimeError(
            f"Агенту переданы ключи записи: {', '.join(leaked)}. Используйте .env.agent"
        )


def onec_read(source: SourceClient, collection: str, period: str | None = None) -> dict[str, Any]:
    """Прочитать коллекцию 1С; для charges/payments можно ограничить месяцем YYYY-MM."""
    if collection not in COLLECTIONS:
        raise ValueError(f"collection должна быть одной из {COLLECTIONS}")
    _check_period(period)
    try:
        rows = source.fetch(collection)
    except SourceError as error:
        return {"status": "error", "source": source.base_url, "error": str(error)}
    if period and collection == "charges":
        rows = [row for row in rows if row.get("period") == period]
    elif period and collection == "payments":
        rows = [row for row in rows if str(row.get("date", "")).startswith(period)]
    return {
        "status": "ok",
        "source": source.base_url,
        "collection": collection,
        "period": period,
        "count": len(rows),
        "rows": rows,
    }


def pg_read(reader_dsn: str, query: str, **params: Any) -> dict[str, Any]:
    """Выполнить именованный параметризованный запрос от agent_reader."""
    if query not in QUERIES:
        raise ValueError(f"Неизвестный запрос {query!r}; доступны: {sorted(QUERIES)}")
    sql, required = QUERIES[query]
    values = {name: params.get(name) for name in required}
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Для {query} нужны параметры: {', '.join(missing)}")
    if "period" in values:
        _check_period(values["period"])
    if "limit" in values:
        values["limit"] = max(1, min(int(values["limit"]), 100))
    if "run_id" in values:
        values["run_id"] = str(uuid.UUID(str(values["run_id"])))
    try:
        with psycopg.connect(reader_dsn) as conn:
            conn.read_only = True  # второй барьер поверх прав роли
            cursor = conn.execute(sql, values)
            columns = [column.name for column in cursor.description]
            rows = [dict(zip(columns, map(_jsonable, row), strict=True)) for row in cursor]
    except psycopg.Error as error:
        return {"status": "error", "query": query, "error": f"{type(error).__name__}: {error}"}
    return {"status": "ok", "query": query, "params": values, "count": len(rows), "rows": rows}


def validate_source(source: SourceClient) -> dict[str, Any]:
    """Проверить данные 1С правилами валидации, ничего не импортируя."""
    try:
        dataset = source.fetch_all()
    except SourceError as error:
        return {"status": "error", "source": source.base_url, "error": str(error)}
    problems = [problem.as_dict() for problem in run_validation(dataset)]
    return {
        "status": "problems" if problems else "ok",
        "source": source.base_url,
        "counts": {name: len(rows) for name, rows in dataset.items()},
        "rules": [rule.name for rule in list_rules() if rule.stage == "validate"],
        "problems": problems,
    }


def reconcile(source: SourceClient, reader_dsn: str, period: str) -> dict[str, Any]:
    """Та же сверка, что в UI; отчёт сохраняется в файл (в БД агент писать не может)."""
    report = run_reconciliation(period, source, reader_dsn)
    path = save_report_file(report, REPORTS_DIR)
    return {**report.as_dict(), "report_file": str(path.relative_to(REPORTS_DIR.parent.parent))}


def rules() -> list[dict[str, str]]:
    return [rule.__dict__ for rule in list_rules()]


def default_source() -> SourceClient:
    return SourceClient(config.source_settings())


def _check_period(period: str | None) -> None:
    if period is not None and not PERIOD_RE.match(period):
        raise ValueError(f"Период {period!r} должен быть в формате YYYY-MM")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
