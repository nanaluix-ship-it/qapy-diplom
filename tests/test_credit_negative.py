import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from faker import Faker

fake = Faker(locale="ru_RU")

# Константы
BASE_URL = "http://localhost:8080"
DECLINED_CARD = "4444 4444 4444 4442"

BUY_CREDIT_BUTTON = (
    By.XPATH,
    "//button[.//span[normalize-space(text())='Купить в кредит']] | "
    "//*[normalize-space(text())='Купить в кредит']"
)
CONTINUE_BUTTON = (
    By.XPATH,
    "//button[contains(., 'Продолжить')] | //*[contains(text(), 'Продолжить')]"
)
CARD_INPUT = (By.CSS_SELECTOR, "input[placeholder='0000 0000 0000 0000']")

ERROR_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'отказал')]")
SUCCESS_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'Успешно')]")

# Банк отвечает с искусственной задержкой
BANK_TIMEOUT = 45
DB_SETTLE_TIMEOUT = 15


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


def open_credit_form():
    """Открывает браузер и форму кредитной покупки, возвращает (driver, wait)."""
    options = Options()
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    driver.get(BASE_URL)
    wait = WebDriverWait(driver, 15)

    wait.until(EC.element_to_be_clickable(BUY_CREDIT_BUTTON)).click()
    return driver, wait


def _find_owner_field(driver):
    """Ищет поле «Владелец»: по плейсхолдеру, затем по позиции в форме."""
    for selector in ("input[placeholder*='Дмитрий']",
                     "input[placeholder*='John']",
                     "input[placeholder*='Ivan']"):
        fields = driver.find_elements(By.CSS_SELECTOR, selector)
        if fields:
            return fields[0]
    inputs = driver.find_elements(By.CSS_SELECTOR, "form input")
    if len(inputs) >= 4:
        return inputs[3]
    raise NoSuchElementException("Не удалось найти поле владельца карты")


def fill_credit_form(driver, wait, card=None, month=None, year=None,
                     owner=None, cvc=None):
    """Заполняет только переданные поля формы кредита и нажимает «Продолжить».

    Незаполненные поля остаются пустыми — так тестируется валидация.
    """
    fields = {
        "card": (wait.until(EC.presence_of_element_located(CARD_INPUT)), card),
        "month": (driver.find_element(By.CSS_SELECTOR, "input[placeholder='08']"), month),
        "year": (driver.find_element(By.CSS_SELECTOR, "input[placeholder='22']"), year),
        "owner": (_find_owner_field(driver), owner),
        "cvc": (driver.find_element(By.CSS_SELECTOR, "input[placeholder='999']"), cvc),
    }
    for name, (element, value) in fields.items():
        if value is not None:
            element.clear()
            element.send_keys(value)

    continue_btn = wait.until(EC.element_to_be_clickable(CONTINUE_BUTTON))
    continue_btn.click()


def _visible_validation_errors(driver):
    """Возвращает тексты видимых подполевых ошибок валидации."""
    return [
        el.text.strip()
        for el in driver.find_elements(By.CSS_SELECTOR, ".input__sub")
        if el.is_displayed() and el.text.strip()
    ]


def _wait_for_new_credit_requests(run_sql, before_created,
                                  timeout=DB_SETTLE_TIMEOUT):
    """Ищет записи credit_request_entity, созданные ПОСЛЕ отправки формы.

    Возвращает список найденных записей (может быть пустым).
    """
    deadline = time.monotonic() + timeout
    rows = []
    while time.monotonic() < deadline:
        rows = _parse_rows(run_sql(
            f"SELECT id, status, bank_id, created FROM credit_request_entity "
            f"WHERE created > '{before_created}';"
        ))
        if rows:
            return rows
        time.sleep(1)
    return []


def _dump_evidence(driver, label):
    """Сохраняет скриншот и печатает видимые уведомления как доказательство."""
    os_dir = "screenshots"
    import os
    os.makedirs(os_dir, exist_ok=True)
    driver.save_screenshot(f"{os_dir}/{label}.png")
    print(f"\n=== Доказательство {label} ===")
    for el in driver.find_elements(By.CSS_SELECTOR, "[class*='notification']"):
        text = (el.text or "").strip()
        if text and el.is_displayed():
            print(repr(text), "| class=", el.get_attribute("class"))


@pytest.mark.xfail(
    reason="issue #1: declined-кредит обрабатывается как успешный, "
           "уведомление об отказе не показывается",
    strict=False,
)
def test_5_1_credit_declined_shows_error():
    """5.1: кредит по отклонённой карте → должно появиться уведомление
    об отказе. Упадёт и станет x — это документированное ожидание бага #1."""
    driver, wait = open_credit_form()
    try:
        fill_credit_form(driver, wait,
                         card=DECLINED_CARD, month="12", year="26",
                         owner=fake.first_name() + " " + fake.last_name(),
                         cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        error_msg = bank_wait.until(
            EC.visibility_of_element_located(ERROR_NOTIFICATION))
        assert "отказал" in error_msg.text, (
            f"Текст уведомления не содержит 'отказал': {error_msg.text!r}"
        )
        print(f"\n[5.1] Уведомление об отказе найдено: {error_msg.text!r}")
    except TimeoutException:
        _dump_evidence(driver, "issue1_credit_no_error_notification")
        raise
    finally:
        driver.quit()


def test_5_2_credit_declined_does_not_show_success():
    """5.2: баг-репродукция (issue #1, кредит) — UI не должен показывать
    «Успешно» при отклонённой кредитной операции. Красный тест = доказательство
    бага в кредитном сценарии."""
    driver, wait = open_credit_form()
    try:
        fill_credit_form(driver, wait,
                         card=DECLINED_CARD, month="12", year="26",
                         owner=fake.first_name() + " " + fake.last_name(),
                         cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            success_msg = bank_wait.until(
                EC.visibility_of_element_located(SUCCESS_NOTIFICATION))
        except TimeoutException:
            print("\n[5.2] «Успешно» не появилось — баг в кредитном "
                  "сценарии не воспроизвёлся")
            return

        _dump_evidence(driver, "issue1_credit_success_on_declined")

        full_text = success_msg.text
        assert False, (
            f"БАГ ПОДТВЕРЖДЁН (issue #1, кредитный сценарий): UI показал "
            f"уведомление успешной операции (class="
            f"{success_msg.get_attribute('class')!r}, текст: {full_text!r}) "
            f"при отклонённой кредитной операции. Скриншот: "
            f"screenshots/issue1_credit_success_on_declined.png"
        )
    finally:
        driver.quit()


def test_5_3_credit_request_declined_in_db(run_sql):
    """5.3: после отклонённого кредита в credit_request_entity создаётся
    запись со статусом DECLINED (слой данных корректен)."""
    driver, wait = open_credit_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM credit_request_entity "
            "ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_credit_form(driver, wait,
                         card=DECLINED_CARD, month="12", year="26",
                         owner=fake.first_name() + " " + fake.last_name(),
                         cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))

        new_rows = _wait_for_new_credit_requests(run_sql, before_created)
        assert new_rows, "В credit_request_entity не появилась новая запись"

        for row in new_rows:
            assert row["status"] == "DECLINED", (
                f"Ожидали DECLINED, получили {row['status']!r} (id={row['id']})"
            )
        print(f"\n[5.3] OK: {len(new_rows)} заявок со статусом DECLINED "
              f"(id={new_rows[0]['id']}, bank_id={new_rows[0]['bank_id']})")
    finally:
        driver.quit()


@pytest.mark.xfail(
    reason="issue #2: order_entity получает запись даже для отклонённой "
           "кредитной операции",
    strict=False,
)
def test_5_4_no_order_for_declined_credit(run_sql):
    """5.4: после отклонённого кредита заказа в order_entity быть не должно.
    Упадёт и станет x — это документированное ожидание бага #2."""
    driver, wait = open_credit_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM credit_request_entity "
            "ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_credit_form(driver, wait,
                         card=DECLINED_CARD, month="12", year="26",
                         owner=fake.first_name() + " " + fake.last_name(),
                         cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))

        new_rows = _wait_for_new_credit_requests(run_sql, before_created)
        assert new_rows, "В credit_request_entity не появилась новая запись"
        latest = new_rows[0]
        assert latest["status"] == "DECLINED", (
            f"Ожидали DECLINED, получили {latest['status']!r}"
        )
        bank_id = latest["bank_id"]

        time.sleep(3)  # даём приложению попытаться создать заказ

        orders = _parse_rows(run_sql(
            f"SELECT id, payment_id, created FROM order_entity "
            f"WHERE payment_id='{bank_id}';"
        ))
        if orders:
            print(f"\n=== Доказательство issue #2: заказы для отклонённой "
                  f"заявки {latest['id']} ===")
            for o in orders:
                print(o)
        assert not orders, (
            f"БАГ ПОДТВЕРЖДЁН (issue #2): для отклонённой кредитной заявки "
            f"{latest['id']} (bank_id={bank_id}) создана запись в "
            f"order_entity: {orders}"
        )
        print(f"\n[5.4] OK: заказов для отклонённой заявки {latest['id']} нет")
    finally:
        driver.quit()


def test_5_5_credit_empty_fields_validation():
    """5.5: пустая кредитная форма → ошибки валидации под полями,
    заявка в банк не отправляется."""
    driver, wait = open_credit_form()
    try:
        buttons = driver.find_elements(*CONTINUE_BUTTON)
        assert buttons, "Кнопка «Продолжить» не найдена"
        buttons[0].click()

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".input_invalid")))
        errors = _visible_validation_errors(driver)
        assert errors, "Подполевые подсказки об ошибках не показаны"
        assert len(errors) >= 4, (
            f"Ожидали ошибки минимум под 4 полями, показали: {errors}"
        )
        print(f"\n[5.5] OK: валидация пустой формы: {errors}")
    finally:
        driver.quit()
