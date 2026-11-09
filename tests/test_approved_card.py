import os
import time
from datetime import date

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from conftest import (
    make_driver, open_payment_form, fill_card_form,
    APPROVED_CARD, SUCCESS_NOTIFICATION, BANK_TIMEOUT,
)

BASE_URL = "http://localhost:8080"
TOUR_PRICE_KOP = 4500000  # 45 000 ₽ в копейках


def _yy(year: int) -> str:
    """Год в двузначном формате для поля карты: 26, а не 2026.

    Поле «Год» ограничено двумя символами — четырёхзначный ввод
    обрезается до '20' и дата превращается в 2020-й.
    """
    return f"{year % 100:02d}"


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


def test_2_1_approved_card_payment(run_sql):
    """2.1: одобренная карта → «Успешно», в payment_entity запись APPROVED."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_payment_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            msg = bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            _dump_visible_texts(driver, "2.1")
            raise
        assert "Успешно" in msg.text, f"Ожидали 'Успешно', получили: {msg.text!r}"

        time.sleep(2)  # даём шлюзу записать транзакцию

        rows = _parse_rows(run_sql(
            "SELECT id, status, amount FROM payment_entity "
            "ORDER BY created DESC LIMIT 1;"
        ))
        assert rows, "В payment_entity нет записей"
        latest = rows[0]
        assert latest["status"] == "APPROVED", (
            f"Ожидали APPROVED, получили {latest['status']!r}"
        )
        assert latest["amount"] == str(TOUR_PRICE_KOP), (
            f"Сумма не совпадает с ценой тура: {latest['amount']!r} "
            f"(ожидали {TOUR_PRICE_KOP})"
        )
        print(f"\n[2.1] OK: payment {latest['id']}, "
              f"status={latest['status']}, amount={latest['amount']}")
    finally:
        driver.quit()


def test_2_2_boundary_december(run_sql):
    """2.2a: граничный месяц 12 текущего года — форма отправляется, банк отвечает."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        month, year = "12", _yy(date.today().year)
        driver.get(BASE_URL)
        open_payment_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD, month=month, year=year)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            msg = bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
            assert "Успешно" in msg.text
            print(f"\n[2.2a] OK: срок {month}/{year} принят банком")
        except TimeoutException:
            _dump_visible_texts(driver, f"2.2a_{month}{year}")
            raise
    finally:
        driver.quit()


def test_2_2_boundary_january_next_year(run_sql):
    """2.2b: срок 01 следующего года — валидная дата на границе года, принята банком."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        next_year = _yy(date.today().year + 1)
        driver.get(BASE_URL)
        open_payment_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD, month="01", year=next_year)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            msg = bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
            assert "Успешно" in msg.text
            print(f"\n[2.2b] OK: срок 01/{next_year} принят банком")
        except TimeoutException:
            _dump_visible_texts(driver, "2.2b")
            raise
    finally:
        driver.quit()


def test_2_3_order_linked_to_payment(run_sql):
    """2.3: после успешной оплаты в order_entity появляется запись,
    связанная с payment_entity через transaction_id."""
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(BASE_URL)
        open_payment_form(driver, wait)
        fill_card_form(driver, wait, APPROVED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            _dump_visible_texts(driver, "2.3")
            raise
        time.sleep(2)

        payments = _parse_rows(run_sql(
            "SELECT id, transaction_id FROM payment_entity "
            "ORDER BY created DESC LIMIT 1;"
        ))
        assert payments, "Нет записи в payment_entity"
        transaction_id = payments[0]["transaction_id"]

        # Смотрим структуру order_entity, чтобы не гадать с колонками
        desc = _parse_rows(run_sql("DESCRIBE order_entity;"))
        columns = [r["Field"] for r in desc]
        print(f"\n[2.3] Колонки order_entity: {columns}")

        orders = _parse_rows(run_sql("SELECT * FROM order_entity;"))
        assert orders, "order_entity пуст — оплата не создала заказ"

        matched = [o for o in orders
                   if o.get("payment_id") == transaction_id]
        assert matched, (
            f"В order_entity нет записи с payment_id={transaction_id}. "
            f"Все записи: {orders}"
        )
        print(f"[2.3] OK: заказ связан с платежом {transaction_id}")
    finally:
        driver.quit()
