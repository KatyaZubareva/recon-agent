# recon-agent

Сверка начислений 1С ↔ PostgreSQL: импорт из опубликованного HTTP-сервиса 1С, сверка за месяц,
веб-страница и CLI-агент с read-only инструментами. Условие: `fullstack.pdf`, контракт: `CONTRACT.md`.

## Стек
- Backend: Python 3.12, uv 0.11.6, FastAPI. Frontend: React + TypeScript.
- Отчётная БД: PostgreSQL 17 (Compose, `localhost:5543/reporting`).
- Источник: 1С 8.3.27.2342 (сервер Linux x86_64 в Docker под amd64), HTTP-сервис GET `/accounts`, `/charges`, `/payments`.
- `source-mock` (`localhost:8093`) — только для разработки и автотестов, НЕ замена 1С.

## Команды
```bash
cp .env.example .env                    # заполнить ONEC_*
docker compose up -d --build --wait     # mock + postgres
uv sync --frozen && uv run pytest       # тесты
uv run ruff check .                     # линтер
uv run --env-file .env python scripts/preflight.py --real   # проверка настоящей 1С
```

## Правила
- Суммы — только целые копейки (`int`/`Decimal`), никаких `float`.
- Арифметика и проверки — в коде/SQL, не в модели.
- Агент — только чтение: роль `agent_reader`, пароль импортёра ему не передаётся.
- Ошибка источника ≠ пустой список: статус ошибки, а не «расхождений нет».
- Mock не выдаётся за интеграцию с 1С; недоступность — `BLOCKED` с причиной.
- Не коммитить `.env`, пароли, ключи, `*.lic`, дистрибутивы 1С.
- Маленькие коммиты, сообщения на русском. Перед `git push` — спросить.
- Новые .md не плодить: README, CLAUDE, TIMELOG, AI_USAGE + два domain-skill.
