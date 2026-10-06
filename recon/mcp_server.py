"""MCP-сервер для Claude Code: инструменты чтения 1С, чтения PostgreSQL и сверки.

Запуск (stdio) прописан в .mcp.json:
    uv run --env-file .env.agent python -m recon.mcp_server
В .env.agent только read-only учётки (scripts/make_agent_env.py); при наличии ключей
записи сервер не стартует.
"""

import os
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from recon import agent_tools, config

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

server = MCPServer(
    "recon",
    instructions=(
        "Инструменты сверки начислений 1С ↔ PostgreSQL. Только чтение. "
        "Суммы — целые копейки; арифметику выполняют инструменты, не модель. "
        "Скиллы: data-validation (проверка данных), recon-report (сверка и отчёт)."
    ),
)


def _guarded(call: Callable[[], Any]) -> Any:
    """Неверные параметры — понятный отказ агенту, а не обезличенная ошибка инструмента."""
    try:
        return call()
    except ValueError as error:
        return {"status": "rejected", "error": str(error)}


@server.tool(annotations=READ_ONLY)
def onec_read(
    collection: Literal["accounts", "charges", "payments"], period: str | None = None
) -> dict:
    """Прочитать коллекцию из опубликованного HTTP-сервиса 1С (пользователь reader).

    period (YYYY-MM) ограничивает начисления месяцем, а платежи — месяцем даты платежа.
    """
    return _guarded(lambda: agent_tools.onec_read(agent_tools.default_source(), collection, period))


@server.tool(annotations=READ_ONLY)
def pg_read(
    query: Literal[
        "accounts",
        "charges_by_period",
        "charge_by_id",
        "totals_by_period",
        "payments",
        "import_runs",
        "recon_runs",
        "recon_discrepancies",
    ],
    period: str | None = None,
    record_id: str | None = None,
    run_id: str | None = None,
    limit: int = 10,
) -> dict:
    """Именованный параметризованный SELECT в отчётной PostgreSQL от роли agent_reader.

    Параметры: charges_by_period/totals_by_period — period; charge_by_id — record_id;
    import_runs/recon_runs — limit; recon_discrepancies — run_id. Произвольный SQL недоступен.
    """
    return _guarded(
        lambda: agent_tools.pg_read(
            config.reader_dsn(),
            query,
            period=period,
            record_id=record_id,
            run_id=run_id,
            limit=limit,
        )
    )


@server.tool(annotations=READ_ONLY)
def validate_source() -> dict:
    """Проверить данные 1С всеми правилами валидации (без импорта). Скилл data-validation."""
    return agent_tools.validate_source(agent_tools.default_source())


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def run_reconciliation(period: str) -> dict:
    """Сверить начисления за месяц YYYY-MM: 1С против PostgreSQL. Скилл recon-report.

    Та же логика, что у веб-страницы. Возвращает отчёт (run_id, статус, итоги обеих сторон,
    расхождения с ID и значениями); копия сохраняется в artifacts/reports/.
    """
    return _guarded(
        lambda: agent_tools.reconcile(agent_tools.default_source(), config.reader_dsn(), period)
    )


@server.tool(annotations=READ_ONLY)
def list_rules() -> list[dict]:
    """Список зарегистрированных правил валидации и сверки."""
    return agent_tools.rules()


def main() -> None:
    agent_tools.ensure_read_only_environment(dict(os.environ))
    server.run("stdio")


if __name__ == "__main__":
    main()
