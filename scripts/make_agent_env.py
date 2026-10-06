"""Создаёт .env.agent для MCP-сервера агента: только read-only ключи из .env.

    python3 scripts/make_agent_env.py

Пароль импортёра PostgreSQL и администратора 1С в .env.agent не попадают.
"""

from pathlib import Path

ALLOWED = (
    "ONEC_BASE_URL", "ONEC_USER", "ONEC_PASSWORD",
    "ONEC_ACCOUNTS_PATH", "ONEC_CHARGES_PATH", "ONEC_PAYMENTS_PATH",
    "RECON_READER_DSN",
)  # fmt: skip

root = Path(__file__).resolve().parent.parent
values = {}
for line in (root / ".env").read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() in ALLOWED:
        values[key.strip()] = value.strip()
missing = [key for key in ALLOWED if not values.get(key)]
if missing:
    raise SystemExit(f"В .env не заполнены: {', '.join(missing)}")
header = "# Сгенерировано scripts/make_agent_env.py: только read-only доступ для агента.\n"
(root / ".env.agent").write_text(header + "".join(f"{k}={values[k]}\n" for k in ALLOWED))
print(f"Создан .env.agent: {', '.join(ALLOWED)}")
