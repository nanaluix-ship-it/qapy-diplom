import os
import time

import pytest
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from conftest import (
    make_driver, open_credit_form, fill_card_form,
    APPROVED_CARD, SUCCESS_NOTIFICATION, BANK_TIMEOUT,
)

BASE_URL = "http://localhost:8080"
DB_SETTLE_TIMEOUT = 15  # сколько ждём появления записи в БД


def _parse_rows(sql_output):
    """Парсит табличный вывод mysql -e в список словарей."""
    lines = [l for l in sql_output.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append(dict(zip(headers, values)))
    return rows


def _dump_visible_texts(driver, label):
    """Печатает видимые тексты со страницы и сохраняет скриншот."""
    print(f"\n=== ДИАГНОСТИКА {label}: что на странице ===")
    for el in driver.find_elements(By.CSS_SELECTOR, "span, div, p"):
        text = (el.text or "").strip()
        if el.is_displayed() and 0 < len(text) < 80:
            print(repr(text), "| class=", el.get_attribute("class"))
    os.makedirs("screenshots", exist_ok=True)
    safe_label = label.replace("/", "")
    driver.save_screenshot(f"screenshots/diag_{safe_label}.png")


def _wait_for_credit_request(run_sql, timeout=DB_SETTLE_TIMEOUT):
    """Ждёт появления записи в credit_request_entity, возвращает последнюю."""
    deadline = time.monotonic() + timeout
    last_rows = []
    while time.monotonic() < deadline:
        last_rows = _parse_rows(run_sql(
            "SELECT id, status, bank_id FROM credit_request_entity "
            "ORDER BY created DESC LIMIT 1;"
        ))
        if last_rows:
            return last_rows[0]
        time.sleep(1)
    return None


@pytest.mark.skip(reason="диагностический тест, запускать вручную")
def test_4_0_diagnostic_credit_state(run_sql):
    """Диагностика: одна кредитная покупка и полный дамп состояния БД.

    Запуск вручную:
    pytest tests/test_credit_purchase.py::test_4_0_diagnostic_credit_state -v -s
    """
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_credit_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            msg = bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
            print(f"\nУведомление: {msg.text!r}")
        except TimeoutException:
            _dump_visible_texts(driver, "4.0")
            raise

        time.sleep(3)

        print("\n=== credit_request_entity, последние 3 ===")
        for r in _parse_rows(run_sql(
                "SELECT id, bank_id, created, status FROM credit_request_entity "
                "ORDER BY created DESC LIMIT 3;"
        )):
            print(r)

        print("\n=== payment_entity, последние 3 ===")
        for r in _parse_rows(run_sql(
                "SELECT id, status, transaction_id, created FROM payment_entity "
                "ORDER BY created DESC LIMIT 3;"
        )):
            print(r)

        print("\n=== order_entity, последние 3 ===")
        for r in _parse_rows(run_sql(
                "SELECT id, credit_id, payment_id, created FROM order_entity "
                "ORDER BY created DESC LIMIT 3;"
        )):
            print(r)

        print("\n=== ВЫВОД: order_entity.payment_id хранит идентификатор "
              "банковской операции (для кредита это bank_id из "
              "credit_request_entity); колонка credit_id не заполняется ===")
    finally:
        driver.quit()


def test_4_1_credit_approved_card(run_sql):
    """4.1: «Купить в кредит», одобренная карта → «Успешно»,
    в credit_request_entity запись со статусом APPROVED."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_credit_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            msg = bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            _dump_visible_texts(driver, "4.1")
            raise
        assert "Успешно" in msg.text, f"Ожидали 'Успешно', получили: {msg.text!r}"

        latest = _wait_for_credit_request(run_sql)
        assert latest is not None, "В credit_request_entity нет записей"
        assert latest["status"] == "APPROVED", (
            f"Ожидали APPROVED, получили {latest['status']!r} (id={latest['id']})"
        )
        print(f"\n[4.1] OK: credit_request {latest['id']}, status={latest['status']}")
    finally:
        driver.quit()


def test_4_2_order_linked_to_credit(run_sql):
    """4.2: после успешного кредита в order_entity появляется запись,
    связанная с кредитной операцией через идентификатор банковской операции
    (order_entity.payment_id == credit_request_entity.bank_id).

    Примечание: order_entity.credit_id не заполняется — связность
    обеспечивается через bank_id. Зафиксировано как наблюдение по схеме данных.
    """
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_credit_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            _dump_visible_texts(driver, "4.2")
            raise

        latest = _wait_for_credit_request(run_sql)
        assert latest is not None, "Нет записи в credit_request_entity"
        bank_id = latest["bank_id"]
        assert bank_id and bank_id != "NULL", (
            f"bank_id пуст у заявки {latest['id']} — нечем связать заказ"
        )

        # Заказ записывается почти мгновенно, но ждём до DB_SETTLE_TIMEOUT секунд
        deadline = time.monotonic() + DB_SETTLE_TIMEOUT
        orders = []
        while time.monotonic() < deadline:
            orders = _parse_rows(run_sql(
                f"SELECT id, credit_id, payment_id, created FROM order_entity "
                f"WHERE payment_id='{bank_id}';"
            ))
            if orders:
                break
            time.sleep(1)

        if not orders:
            print(f"\n=== ДИАГНОСТИКА 4.2: заказ с payment_id={bank_id} не найден ===")
            print("Последние записи order_entity:")
            for o in _parse_rows(run_sql(
                    "SELECT id, credit_id, payment_id, created FROM order_entity "
                    "ORDER BY created DESC LIMIT 5;"
            )):
                print(o)
        assert orders, (
            f"В order_entity нет записи, связанной с банковской операцией "
            f"{bank_id} (заявка {latest['id']}) за {DB_SETTLE_TIMEOUT} секунд"
        )
        order = orders[0]
        print(f"\n[4.2] OK: заказ {order['id']} связан с операцией {bank_id}; "
              f"credit_id в заказе = {order['credit_id']} (не заполняется)")
    finally:
        driver.quit()


def test_4_3_credit_bank_id_filled(run_sql):
    """4.3: в approved-заявке заполнен bank_id — банк подтвердил операцию.
    Сумму заявки проверить нельзя: в credit_request_entity колонки amount нет
    (сумма подтверждается на стороне debit-сценария, пункт 2.1)."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_credit_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            _dump_visible_texts(driver, "4.3")
            raise

        latest = _wait_for_credit_request(run_sql)
        assert latest is not None, "Нет записи в credit_request_entity"
        assert latest["status"] == "APPROVED", (
            f"Ожидали APPROVED, получили {latest['status']!r}"
        )
        assert latest.get("bank_id"), (
            f"bank_id пуст у заявки {latest['id']} — банк не подтвердил операцию"
        )
        print(f"[4.3] OK: credit_request {latest['id']}, "
              f"status=APPROVED, bank_id={latest['bank_id']}")
    finally:
        driver.quit()
