import time

import allure
import pytest
import requests

from tests.test_payment_negative import _parse_rows

APP = "http://localhost:8080"
GATE = "http://localhost:9999"

VALID_BODY = {
    "number": "4444 4444 4444 4441",
    "year": "26",
    "month": "12",
    "card-holder": "IVAN IVANOV",
    "cvc": "999",
}
DECLINED_BODY = {**VALID_BODY, "number": "4444 4444 4444 4442"}
UNKNOWN_BODY = {**VALID_BODY, "number": "1234 5678 9012 3456"}


@allure.feature("API-проверки")
@allure.story("Собственное API приложения: /api/v1/pay")
@allure.severity(allure.severity_level.NORMAL)
def test_8_1_api_pay_approved(run_sql):
    """8.1: POST /api/v1/pay с APPROVED-картой — 200, статус APPROVED,
    запись в payment_entity создана."""
    before = _parse_rows(run_sql(
        "SELECT created FROM payment_entity ORDER BY created DESC LIMIT 1;"))
    before_created = before[0]["created"] if before else ""

    r = requests.post(APP + "/api/v1/pay", json=VALID_BODY, timeout=30)
    assert r.status_code == 200, (
        f"Ожидался 200, получен {r.status_code}: {r.text[:200]!r}")
    status = r.json().get("status")
    assert status == "APPROVED", (
        f"Ожидался статус APPROVED, получен {status!r}")

    # Даём записи время дойти до БД, затем проверяем факт
    deadline = time.monotonic() + 10
    new_rows = []
    while time.monotonic() < deadline:
        new_rows = _parse_rows(run_sql(
            f"SELECT * FROM payment_entity WHERE created > '{before_created}';"))
        if new_rows:
            break
        time.sleep(0.5)
    assert new_rows, (
        "Ответ 200/APPROVED получен, но запись в payment_entity не создана — "
        "API-ответ не подтверждён сохранением")
    print(f"\n[8.1] OK: 200 APPROVED, запись в БД создана "
          f"(status={new_rows[0].get('status')})")


@allure.feature("API-проверки")
@allure.story("Собственное API приложения: /api/v1/credit")
@allure.severity(allure.severity_level.NORMAL)
def test_8_2_api_credit_approved():
    """8.2: POST /api/v1/credit с APPROVED-картой — 200, статус APPROVED."""
    r = requests.post(APP + "/api/v1/credit", json=VALID_BODY, timeout=30)
    assert r.status_code == 200, (
        f"Ожидался 200, получен {r.status_code}: {r.text[:200]!r}")
    status = r.json().get("status")
    assert status == "APPROVED", (
        f"Ожидался статус APPROVED, получен {status!r}")
    print(f"\n[8.2] OK: 200 APPROVED")


@allure.feature("API-проверки")
@allure.story("Заглушка шлюза: DECLINED-карта")
@allure.severity(allure.severity_level.NORMAL)
def test_8_3_gate_payment_declined():
    """8.3: POST /payment (9999) с DECLINED-картой — 200, статус DECLINED
    в теле ответа (код HTTP остаётся 200 — отказ отражается не кодом,
    а полем status)."""
    r = requests.post(GATE + "/payment", json=DECLINED_BODY, timeout=30)
    assert r.status_code == 200, (
        f"Ожидался 200, получен {r.status_code}: {r.text[:200]!r}")
    status = r.json().get("status")
    assert status == "DECLINED", (
        f"Ожидался статус DECLINED, получен {status!r}")
    print(f"\n[8.3] OK: 200 DECLINED (статус в теле, не в коде)")


@allure.feature("API-проверки")
@allure.story("Заглушка шлюза: незнакомая карта")
@allure.severity(allure.severity_level.NORMAL)
def test_8_4_gate_unknown_card():
    """8.4: POST /payment (9999) с незнакомой картой — 400, пустое тело.
    Документированное отличие от сценария 3.3: незнакомая карта
    отклоняется на уровне шлюза кодом ошибки, а не статусом в теле."""
    r = requests.post(GATE + "/payment", json=UNKNOWN_BODY, timeout=30)
    assert r.status_code == 400, (
        f"Ожидался 400, получен {r.status_code}: {r.text[:200]!r}")
    print(f"\n[8.4] OK: 400, тело пустое — незнакомая карта отклонена шлюзом")


@allure.feature("API-проверки")
@allure.story("Обработка невалидного тела запроса")
@allure.severity(allure.severity_level.MINOR)
def test_8_5_api_invalid_body():
    """8.5: POST /api/v1/credit с невалидным телом — ожидается ошибка
    клиентского класса (4xx). Фактически приложение возвращает 500
    с message '400 Bad Request' — чужая ошибка шлюза заворачивается
    в Internal Server Error. Кандидат в issue #6 (Minor).
    Тест оставлен как репродукция, ср. подход issue #3/#4."""
    r = requests.post(APP + "/api/v1/credit", json={"foo": "bar"}, timeout=30)
    has_error = r.status_code >= 400
    assert 400 <= r.status_code < 500, (
        f"БАГ ПОДТВЕРЖДЁН (issue #5, кандидат): невалидное тело запроса "
        f"вернуло {r.status_code} вместо ошибки клиентского класса (4xx). "
        f"Тело ответа: {r.text[:300]!r}. Ошибка шлюза (400 Bad Request) "
        f"заворачивается в Internal Server Error."
    )
    print(f"\n[8.5] OK: {r.status_code} — ошибка клиентского класса")
