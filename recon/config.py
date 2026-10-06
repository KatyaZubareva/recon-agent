"""Настройки из переменных окружения (.env). Пароли в код не зашиваются."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSettings:
    base_url: str
    user: str
    password: str
    paths: dict[str, str]


def source_settings() -> SourceSettings:
    """Источник — опубликованный HTTP-сервис 1С (или mock в тестах/разработке)."""
    return SourceSettings(
        base_url=os.environ.get("ONEC_BASE_URL", ""),
        user=os.environ.get("ONEC_USER", ""),
        password=os.environ.get("ONEC_PASSWORD", ""),
        paths={
            name: os.environ.get(f"ONEC_{name.upper()}_PATH", name)
            for name in ("accounts", "charges", "payments")
        },
    )


def importer_dsn() -> str:
    """Роль importer: пишет данные. Агенту эта переменная не передаётся."""
    return _required("RECON_IMPORTER_DSN")


def reader_dsn() -> str:
    """Роль agent_reader: только SELECT, read-only транзакции на уровне роли."""
    return _required("RECON_READER_DSN")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value
