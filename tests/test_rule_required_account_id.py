import pytest
from conftest import make_source, query, serving

from recon.importer import run_import
from recon.rules import list_rules


def test_rule_is_registered_without_changing_main_scenario():
    assert "required_account_id" in {rule.name for rule in list_rules()}


@pytest.mark.parametrize("missing", [None, ""])
@pytest.mark.parametrize(
    ("entity", "index", "record_id"),
    [
        ("charges", 0, "charge-1"),
        ("payments", 0, "payment-1"),
    ],
)
def test_record_without_account_id_is_rejected_before_import(
    importer_dsn, dataset, entity, index, record_id, missing
):
    if missing is None:
        del dataset[entity][index]["account_id"]
    else:
        dataset[entity][index]["account_id"] = missing

    result = run_import(make_source(serving(dataset)), importer_dsn)

    assert result.status == "rejected"
    assert [(p["rule"], p["record_id"]) for p in result.problems] == [
        ("required_account_id", record_id)
    ]
    assert query(importer_dsn, "SELECT count(*) FROM charges") == [(0,)]


def test_without_the_rule_import_fails_late_in_database(importer_dsn, dataset, monkeypatch):
    # Для сравнения: если правило снять, запись доходит до PostgreSQL и падает на NOT NULL.
    from recon import rules

    rules._load_rule_modules()
    monkeypatch.delitem(rules.VALIDATION_RULES, "required_account_id")
    dataset["charges"][0]["account_id"] = None

    result = run_import(make_source(serving(dataset)), importer_dsn)

    assert result.status == "error"
    assert "NotNullViolation" in result.error
