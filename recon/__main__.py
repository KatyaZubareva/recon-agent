"""CLI: uv run --env-file .env python -m recon <команда>.

Коды возврата: 0 — успех, 1 — найдены проблемы/расхождения, 2 — ошибка (источник, БД).
"""

import argparse
import json
import sys

from recon import config
from recon.db import apply_schema
from recon.importer import run_import
from recon.rules import list_rules
from recon.source import SourceClient, SourceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recon")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("db-init", help="создать таблицы (роль importer)")
    commands.add_parser("import", help="импорт 1С → PostgreSQL (роль importer)")
    commands.add_parser("rules", help="список зарегистрированных правил")
    args = parser.parse_args(argv)

    if args.command == "db-init":
        apply_schema(config.importer_dsn())
        return _print({"status": "ok"}, 0)
    if args.command == "import":
        try:
            source = SourceClient(config.source_settings())
        except SourceError as error:
            return _print({"status": "error", "error": str(error)}, 2)
        result = run_import(source, config.importer_dsn())
        return _print(result.as_dict(), {"ok": 0, "rejected": 1}.get(result.status, 2))
    if args.command == "rules":
        return _print([rule.__dict__ for rule in list_rules()], 0)
    return 2


def _print(payload: object, code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
