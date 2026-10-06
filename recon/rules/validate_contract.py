"""Базовые правила валидации по CONTRACT.md: типы, форматы, уникальность, ссылки."""

import re
from datetime import date

from recon.rules import Problem, validation_rule
from recon.source import Dataset

PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _is_int(value: object) -> bool:
    # bool — подкласс int в Python, его не считаем суммой; float запрещён.
    return type(value) is int


@validation_rule("unique_ids", "id есть, это непустая строка и он уникален в коллекции")
def unique_ids(data: Dataset):
    for entity, rows in data.items():
        seen: set[str] = set()
        for row in rows:
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id:
                yield Problem("unique_ids", entity, None, f"пустой или нестроковый id: {row!r}")
            elif row_id in seen:
                yield Problem("unique_ids", entity, row_id, "id повторяется")
            else:
                seen.add(row_id)


@validation_rule("account_number", "у лицевого счёта есть непустой номер")
def account_number(data: Dataset):
    for row in data["accounts"]:
        number = row.get("account_number")
        if not isinstance(number, str) or not number:
            yield Problem("account_number", "accounts", row.get("id"), "нет account_number")


@validation_rule("integer_amounts", "amount_kopecks — целое число копеек (не float, не строка)")
def integer_amounts(data: Dataset):
    for entity in ("charges", "payments"):
        for row in data[entity]:
            if not _is_int(row.get("amount_kopecks")):
                yield Problem(
                    "integer_amounts",
                    entity,
                    row.get("id"),
                    f"amount_kopecks не целое: {row.get('amount_kopecks')!r}",
                )


@validation_rule("period_format", "period начисления в формате YYYY-MM")
def period_format(data: Dataset):
    for row in data["charges"]:
        period = row.get("period")
        if not isinstance(period, str) or not PERIOD_RE.match(period):
            yield Problem("period_format", "charges", row.get("id"), f"period {period!r}")


@validation_rule("date_format", "date платежа в формате YYYY-MM-DD")
def date_format(data: Dataset):
    for row in data["payments"]:
        value = row.get("date")
        if not _is_iso_date(value):
            yield Problem("date_format", "payments", row.get("id"), f"date {value!r}")


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@validation_rule("account_reference", "заполненный account_id ссылается на импортируемый счёт")
def account_reference(data: Dataset):
    known = {row.get("id") for row in data["accounts"]}
    for entity in ("charges", "payments"):
        for row in data[entity]:
            account_id = row.get("account_id")
            # Пустой account_id — не этого правила (отдельное правило обязательности).
            if account_id and account_id not in known:
                yield Problem(
                    "account_reference", entity, row.get("id"), f"неизвестный счёт {account_id!r}"
                )
