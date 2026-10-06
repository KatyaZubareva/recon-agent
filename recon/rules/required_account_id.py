"""Новое правило (демонстрация расширения): у начисления и платежа обязателен ID счёта.

Без него запись без account_id доходила бы до PostgreSQL и роняла импорт ошибкой
NOT NULL; с ним импорт отклоняется заранее с понятной причиной и ID записи.
Чтобы добавить правило, достаточно этого файла: реестр подхватывает модули пакета сам.
"""

from recon.rules import Problem, validation_rule
from recon.source import Dataset


@validation_rule("required_account_id", "у начисления и платежа заполнен account_id")
def required_account_id(data: Dataset):
    for entity in ("charges", "payments"):
        for row in data[entity]:
            if not row.get("account_id"):
                yield Problem(
                    "required_account_id", entity, row.get("id"), "не заполнен account_id"
                )
