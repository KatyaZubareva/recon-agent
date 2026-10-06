"""Сверка опубликованной 1С с эталоном fixtures/data.json (подготовка 1С, не сверка приложения).

Проверяет: те же записи с теми же ID, связями и суммами, итоги августа 2026 из CONTRACT.md.
Суммы — только int. Код возврата 0 = PASS, 1 = FAIL, 2 = BLOCKED (1С недоступна).
"""

import json
import os
import sys
from pathlib import Path

import httpx

FIXTURES = json.loads((Path(__file__).parent.parent / "fixtures/data.json").read_text())
EXPECTED_AUGUST = {
    "total": 1_140_000,
    "count": 3,
    "by_account": {"10001": 150_000, "20002": 990_000},
}

base = os.environ["ONEC_BASE_URL"].rstrip("/")
auth = (os.environ["ONEC_USER"], os.environ["ONEC_PASSWORD"])

try:
    with httpx.Client(auth=auth, timeout=15) as client:
        real = {}
        for name in ("accounts", "charges", "payments"):
            response = client.get(f"{base}/{name}")
            response.raise_for_status()
            real[name] = response.json()["value"]
except (httpx.HTTPError, KeyError, ValueError) as error:
    print(json.dumps({"status": "BLOCKED", "reason": f"{type(error).__name__}: {error}"}))
    sys.exit(2)

problems = []
for name, expected_rows in FIXTURES.items():
    expected = {row["id"]: row for row in expected_rows}
    actual = {row["id"]: row for row in real[name]}
    if len(actual) != len(real[name]):
        problems.append(f"{name}: повторяющиеся id")
    for row_id in expected.keys() - actual.keys():
        problems.append(f"{name}: нет записи {row_id}")
    for row_id in actual.keys() - expected.keys():
        problems.append(f"{name}: лишняя запись {row_id}")
    for row_id in expected.keys() & actual.keys():
        if expected[row_id] != actual[row_id]:
            problems.append(f"{name}/{row_id}: эталон {expected[row_id]}, 1С {actual[row_id]}")
    for row in real[name]:
        if "amount_kopecks" in row and type(row["amount_kopecks"]) is not int:
            problems.append(
                f"{name}/{row['id']}: amount_kopecks не целое: {row['amount_kopecks']!r}"
            )

numbers = {row["id"]: row["account_number"] for row in real["accounts"]}
august = [row for row in real["charges"] if row["period"] == "2026-08"]
by_account: dict[str, int] = {}
for row in august:
    number = numbers.get(row["account_id"], "?")
    by_account[number] = by_account.get(number, 0) + row["amount_kopecks"]
fact = {
    "total": sum(row["amount_kopecks"] for row in august),
    "count": len(august),
    "by_account": by_account,
}
if fact != EXPECTED_AUGUST:
    problems.append(f"август 2026: эталон {EXPECTED_AUGUST}, 1С {fact}")

print(
    json.dumps(
        {
            "status": "FAIL" if problems else "PASS",
            "source": base,
            "counts": {k: len(v) for k, v in real.items()},
            "august_2026": fact,
            "problems": problems,
        },
        ensure_ascii=False,
        indent=2,
    )
)
sys.exit(1 if problems else 0)
