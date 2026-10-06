"""Реестр правил — механизм расширения.

Новое правило = новая функция с декоратором в любом модуле этого пакета.
Модули пакета импортируются автоматически, основной сценарий (импорт, сверка)
просто перебирает реестр и не меняется при добавлении правил.
"""

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from recon.source import Dataset


@dataclass(frozen=True)
class Problem:
    """Нарушение правила валидации перед импортом."""

    rule: str
    entity: str  # accounts | charges | payments
    record_id: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "entity": self.entity,
            "record_id": self.record_id,
            "message": self.message,
        }


ValidationRule = Callable[[Dataset], Iterable[Problem]]


@dataclass(frozen=True)
class RuleInfo:
    name: str
    stage: str  # validate | reconcile
    description: str


@dataclass(frozen=True)
class Charge:
    id: str
    account_id: str | None
    period: str
    amount_kopecks: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "period": self.period,
            "amount_kopecks": self.amount_kopecks,
        }


@dataclass(frozen=True)
class ReconContext:
    """Что видят правила сверки: начисления выбранного месяца с обеих сторон."""

    period: str
    source: dict[str, Charge]  # 1С, id -> начисление
    target: dict[str, Charge]  # PostgreSQL, id -> начисление


@dataclass(frozen=True)
class Discrepancy:
    """Расхождение: тип, ID записи и значения с каждой стороны (None — записи нет)."""

    type: str
    record_id: str | None
    source: dict[str, Any] | None
    target: dict[str, Any] | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "record_id": self.record_id,
            "source": self.source,
            "target": self.target,
            "message": self.message,
        }


ReconcileRule = Callable[[ReconContext], Iterable[Discrepancy]]

VALIDATION_RULES: dict[str, ValidationRule] = {}
RECONCILE_RULES: dict[str, ReconcileRule] = {}
RULES_INFO: dict[str, RuleInfo] = {}


def validation_rule(name: str, description: str):
    """Регистрирует правило валидации набора данных перед импортом."""

    def register(func: ValidationRule) -> ValidationRule:
        if name in RULES_INFO:
            raise ValueError(f"Правило {name} уже зарегистрировано")
        VALIDATION_RULES[name] = func
        RULES_INFO[name] = RuleInfo(name, "validate", description)
        return func

    return register


def reconcile_rule(name: str, description: str):
    """Регистрирует правило сверки начислений за месяц."""

    def register(func: ReconcileRule) -> ReconcileRule:
        if name in RULES_INFO:
            raise ValueError(f"Правило {name} уже зарегистрировано")
        RECONCILE_RULES[name] = func
        RULES_INFO[name] = RuleInfo(name, "reconcile", description)
        return func

    return register


def run_reconcile_rules(context: ReconContext) -> tuple[list[str], list[Discrepancy]]:
    """Прогоняет все правила сверки; возвращает имена правил и найденные расхождения."""
    _load_rule_modules()
    found: list[Discrepancy] = []
    for rule in RECONCILE_RULES.values():
        found.extend(rule(context))
    return list(RECONCILE_RULES), found


def run_validation(dataset: Dataset) -> list[Problem]:
    _load_rule_modules()
    problems: list[Problem] = []
    for rule in VALIDATION_RULES.values():
        problems.extend(rule(dataset))
    return problems


def list_rules() -> list[RuleInfo]:
    _load_rule_modules()
    return list(RULES_INFO.values())


def _load_rule_modules() -> None:
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module.name}")
