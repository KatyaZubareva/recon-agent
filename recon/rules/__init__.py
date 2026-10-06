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


VALIDATION_RULES: dict[str, ValidationRule] = {}
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
