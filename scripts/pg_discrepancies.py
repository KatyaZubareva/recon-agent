"""Внесение и устранение двух демонстрационных расхождений — ТОЛЬКО в PostgreSQL.

1С (источник) не изменяется. Запуск:
    uv run --env-file .env python scripts/pg_discrepancies.py inject   # внести
    uv run --env-file .env python scripts/pg_discrepancies.py status   # показать август в PG
    uv run --env-file .env python scripts/pg_discrepancies.py restore  # устранить (импорт из 1С)

inject:  удаляет начисление charge-2 и меняет сумму charge-3 (990 000 → 999 000 коп.).
restore: повторный импорт из источника (upsert по id) возвращает обе записи к состоянию 1С.
Скрипт идемпотентен: повторный inject/restore даёт тот же результат.
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # пакет recon из корня репо

from recon import config
from recon.importer import run_import
from recon.source import SourceClient

DELETED_ID = "charge-2"
CHANGED_ID = "charge-3"
CHANGED_AMOUNT = 999_000


def inject(dsn: str) -> dict:
    with psycopg.connect(dsn) as conn, conn.transaction():
        deleted = conn.execute("DELETE FROM charges WHERE id = %s", (DELETED_ID,)).rowcount
        updated = conn.execute(
            "UPDATE charges SET amount_kopecks = %s WHERE id = %s", (CHANGED_AMOUNT, CHANGED_ID)
        ).rowcount
    if updated != 1:
        raise RuntimeError(f"{CHANGED_ID} нет в PostgreSQL — сначала выполните импорт")
    return {
        "deleted": DELETED_ID if deleted else None,
        "changed": {"id": CHANGED_ID, "amount_kopecks": CHANGED_AMOUNT},
    }


def status(dsn: str, period: str = "2026-08") -> list[dict]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id, account_id, amount_kopecks FROM charges WHERE period = %s ORDER BY id",
            (period,),
        ).fetchall()
    return [{"id": r[0], "account_id": r[1], "amount_kopecks": r[2]} for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["inject", "restore", "status"])
    args = parser.parse_args()
    dsn = config.importer_dsn()

    if args.action == "inject":
        result = inject(dsn)
    elif args.action == "restore":
        imported = run_import(SourceClient(config.source_settings()), dsn)
        result = {"import": imported.status, "counts": imported.counts, "error": imported.error}
        if imported.status != "ok":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
    else:
        result = {"period": "2026-08", "charges": status(dsn)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
