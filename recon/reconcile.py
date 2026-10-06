"""Сверка начислений за месяц: 1С (HTTP) против PostgreSQL (роль agent_reader).

Одна функция run_reconciliation используется и веб-страницей (через API), и агентом
(через CLI/MCP). Арифметика — целые копейки в Python, модель ничего не считает.
Статусы: ok — расхождений нет; discrepancies — найдены; error — сверка НЕ выполнена
(источник/БД недоступны или данные нарушают контракт). Итоги «совпадает» при error не выдаются.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from recon.db import connect
from recon.rules import Charge, ReconContext, run_reconcile_rules, run_validation
from recon.source import SourceClient, SourceError

PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@dataclass
class Report:
    run_id: str
    period: str
    status: str = "running"
    started_at: str = field(default_factory=lambda: _now())
    finished_at: str | None = None
    source: dict[str, Any] | None = None  # {"name", "count", "amount_kopecks"}
    target: dict[str, Any] | None = None
    rules: list[str] = field(default_factory=list)
    discrepancies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def run_reconciliation(period: str, source: SourceClient, reader_dsn: str) -> Report:
    if not PERIOD_RE.match(period):
        raise ValueError(f"Период {period!r} должен быть в формате YYYY-MM")
    report = Report(run_id=str(uuid.uuid4()), period=period)
    try:
        source_charges = _source_charges(source, period)
        target_charges = _target_charges(reader_dsn, period)
    except SourceError as error:
        return _fail(report, f"Источник 1С: {error}")
    except psycopg.Error as error:
        return _fail(report, f"PostgreSQL: {type(error).__name__}: {error}")

    report.source = _side(f"Источник ({source.base_url})", source_charges)
    report.target = _side("PostgreSQL", target_charges)
    context = ReconContext(period, source_charges, target_charges)
    report.rules, found = run_reconcile_rules(context)
    report.discrepancies = [item.as_dict() for item in found]
    report.status = "discrepancies" if found else "ok"
    report.finished_at = _now()
    return report


def _source_charges(source: SourceClient, period: str) -> dict[str, Charge]:
    """Начисления месяца из 1С. Данные, нарушающие контракт, — ошибка, а не «пусто»."""
    dataset = {
        "accounts": source.fetch("accounts"),
        "charges": source.fetch("charges"),
        "payments": [],
    }
    problems = run_validation(dataset)
    if problems:
        details = "; ".join(f"{p.record_id}: {p.message}" for p in problems[:5])
        raise SourceError(f"данные не соответствуют контракту ({details})")
    return {
        row["id"]: Charge(row["id"], row.get("account_id"), row["period"], row["amount_kopecks"])
        for row in dataset["charges"]
        if row["period"] == period
    }


def _target_charges(reader_dsn: str, period: str) -> dict[str, Charge]:
    with connect(reader_dsn) as conn:
        rows = conn.execute(
            "SELECT id, account_id, period, amount_kopecks FROM charges WHERE period = %s",
            (period,),
        ).fetchall()
    return {row[0]: Charge(*row) for row in rows}


def _side(name: str, charges: dict[str, Charge]) -> dict[str, Any]:
    return {
        "name": name,
        "count": len(charges),
        "amount_kopecks": sum(c.amount_kopecks for c in charges.values()),
    }


def _fail(report: Report, error: str) -> Report:
    report.status, report.error, report.finished_at = "error", error, _now()
    return report


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_report_db(report: Report, importer_dsn: str) -> None:
    """Сохранить отчёт в recon_runs/recon_discrepancies (UI/API, роль importer)."""
    source, target = report.source or {}, report.target or {}
    with connect(importer_dsn) as conn, conn.transaction():
        conn.execute(
            """INSERT INTO recon_runs (id, period, status, started_at, finished_at, source_count,
                   source_amount_kopecks, target_count, target_amount_kopecks, error, report)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status,
                   finished_at = EXCLUDED.finished_at, source_count = EXCLUDED.source_count,
                   source_amount_kopecks = EXCLUDED.source_amount_kopecks,
                   target_count = EXCLUDED.target_count,
                   target_amount_kopecks = EXCLUDED.target_amount_kopecks,
                   error = EXCLUDED.error, report = EXCLUDED.report""",
            (
                report.run_id,
                report.period,
                report.status,
                report.started_at,
                report.finished_at,
                source.get("count"),
                source.get("amount_kopecks"),
                target.get("count"),
                target.get("amount_kopecks"),
                report.error,
                Jsonb(report.as_dict()),
            ),
        )
        conn.execute("DELETE FROM recon_discrepancies WHERE run_id = %s", (report.run_id,))
        for position, item in enumerate(report.discrepancies):
            conn.execute(
                """INSERT INTO recon_discrepancies
                       (run_id, position, type, record_id, source_value, target_value, message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    report.run_id,
                    position,
                    item["type"],
                    item["record_id"],
                    Jsonb(item["source"]) if item["source"] is not None else None,
                    Jsonb(item["target"]) if item["target"] is not None else None,
                    item["message"],
                ),
            )


def save_report_file(report: Report, directory: Path) -> Path:
    """Сохранить отчёт в JSON-файл (агент: прав на запись в БД у него нет)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"recon-{report.period}-{report.run_id}.json"
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return path
