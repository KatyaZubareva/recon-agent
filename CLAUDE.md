# recon-agent

Сверка начислений 1С ↔ PostgreSQL: импорт из HTTP-сервиса 1С, сверка за месяц, веб-страница
и агент сверки с read-only инструментами. Условие — `fullstack.pdf`, контракт — `CONTRACT.md`,
запуск и устройство — `README.md`.

## Стек
- Backend: Python 3.12, uv 0.11.6, FastAPI, psycopg 3 (`recon/`). Frontend: React + TypeScript, Vite (`frontend/`).
- PostgreSQL 17 в Compose (`localhost:5543/reporting`), схема — `db/schema.sql`.
- 1С 8.3.27.2342: `ibsrv` в Docker (amd64), профиль `onec`, исходники — `onec/config/`.
- `source-mock` — только для разработки и автотестов, НЕ замена 1С.

## Команды
```bash
./onec/restore.sh                                     # 1С с нуля (нужны .env и onec-dist/)
docker compose --profile onec up -d --build --wait    # postgres + 1С + app (:8080)
uv sync --frozen && uv run pytest                     # тесты (нужна postgres)
uv run ruff check . && uv run ruff format recon tests
uv run --env-file .env python -m recon import | reconcile --period 2026-08 | rules
uv run --env-file .env python scripts/pg_discrepancies.py inject | restore | status
cd frontend && npm run build && npm run lint
```

## Правила
- Суммы — только целые копейки (`int`, `bigint`), никаких `float`. Арифметика — в коде/SQL, не в модели.
- Новое правило — новый файл в `recon/rules/` с `@validation_rule` / `@reconcile_rule`; основной сценарий не трогать.
- Импорт и сверка — отдельные действия. Ошибка источника ≠ пустой список: статус `error`.
- Агент сверки — субагент `recon-analyst`, только `mcp__recon__*`; учётки — `.env.agent` (только read-only).
- Mock не выдаётся за интеграцию с 1С; недоступность — `BLOCKED` с причиной.
- Не коммитить `.env*` (кроме `.env.example`), пароли, `*.lic`, дистрибутивы 1С.
- Маленькие коммиты на русском. Перед `git push` — спросить. Новые .md не плодить.
