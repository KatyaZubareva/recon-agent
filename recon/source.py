"""Чтение источника по CONTRACT.md: GET /accounts, /charges, /payments → {"value": [...]}."""

from typing import Any

import httpx

from recon.config import SourceSettings

COLLECTIONS = ("accounts", "charges", "payments")
Row = dict[str, Any]
Dataset = dict[str, list[Row]]


class SourceError(Exception):
    """Источник недоступен или ответил не по контракту. Никогда не равно пустому списку."""


class SourceClient:
    def __init__(self, settings: SourceSettings, client: httpx.Client | None = None):
        if not settings.base_url:
            raise SourceError("Не задан адрес источника ONEC_BASE_URL")
        self.base_url = settings.base_url.rstrip("/")
        self.paths = settings.paths
        auth = (settings.user, settings.password) if settings.user else None
        self._client = client or httpx.Client(auth=auth, timeout=15)

    def fetch(self, collection: str) -> list[Row]:
        url = f"{self.base_url}/{self.paths.get(collection, collection).lstrip('/')}"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as error:
            raise SourceError(f"{collection}: HTTP {error.response.status_code}") from error
        except httpx.HTTPError as error:
            raise SourceError(f"{collection}: {type(error).__name__}: {error}") from error
        except ValueError as error:
            raise SourceError(f"{collection}: ответ не JSON") from error
        rows = body.get("value") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SourceError(f"{collection}: в ответе нет списка value")
        return rows

    def fetch_all(self) -> Dataset:
        """Все три коллекции; любая ошибка прерывает чтение целиком."""
        return {name: self.fetch(name) for name in COLLECTIONS}
