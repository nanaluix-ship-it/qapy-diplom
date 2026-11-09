import os
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

BUY_BUTTON = (By.XPATH, "//*[normalize-space(text())='Купить']")
CONTINUE_BUTTON = (
    By.XPATH,
    "//button[contains(., 'Продолжить')] | //*[contains(text(), 'Продолжить')]"
)
CARD_INPUT = (By.CSS_SELECTOR, "input[placeholder='0000 0000 0000 0000']")

ERROR_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'отказал')]")
SUCCESS_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'Успешно')]")

# Банк отвечает с искусственной задержкой, поэтому ждём уведомления долго
BANK_TIMEOUT = 45


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


def _dump_evidence(driver, label, extra_elements=None):
    """Сохраняет скриншот и печатает видимые элементы как доказательство."""
    os.makedirs("screenshots", exist_ok=True)
    safe_label = label.replace("/", "")
    driver.save_screenshot(f"screenshots/{safe_label}.png")
    print(f"\n=== Доказательство {label} ===")
    for el in (extra_elements or driver.find_elements(
            By.CSS_SELECTOR, ".notification, [class*='notification'], div")):
        text = (el.text or "").strip()
        if text and el.is_displayed() and len(text) < 100:
            print(repr(text), "| class=", el.get_attribute("class"))


def open_card_form():
    """Открывает браузер и форму оплаты, возвращает (driver, wait)."""
    options = Options()
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    driver.get(BASE_URL)
    wait = WebDriverWait(driver, 15)

    wait.until(EC.element_to_be_clickable(BUY_BUTTON)).click()
    return driver, wait


def fill_card_form(driver, wait, card_number):
    """Заполняет поля формы оплаты и нажимает «Продолжить»."""
    card_field = wait.until(EC.presence_of_element_located(CARD_INPUT))
    card_field.clear()
    card_field.send_keys(card_number)

    month_field = driver.find_element(By.CSS_SELECTOR, "input[placeholder='08']")
    year_field = driver.find_element(By.CSS_SELECTOR, "input[placeholder='22']")

    try:
        holder_field = driver.find_element(
            By.CSS_SELECTOR,
            "input[placeholder*='Дмитрий'], "
            "input[placeholder*='John'], "
            "input[placeholder*='Ivan']"
        )
    except NoSuchElementException:
        inputs = driver.find_elements(By.CSS_SELECTOR, "form input")
        if len(inputs) >= 4:
            holder_field = inputs[3]
        else:
            raise NoSuchElementException("Не удалось найти поле владельца карты")

    cvc_field = driver.find_element(By.CSS_SELECTOR, "input[placeholder='999']")

    month_field.clear()
    month_field.send_keys("12")

    year_field.clear()
    year_field.send_keys("26")

    holder_field.clear()
    holder_field.send_keys(fake.first_name() + " " + fake.last_name())

    cvc_field.clear()
    cvc_field.send_keys("999")

    continue_btn = wait.until(EC.element_to_be_clickable(CONTINUE_BUTTON))
    continue_btn.click()


@pytest.mark.xfail(
    reason="issue #1: declined-оплата обрабатывается как успешная, "
           "уведомление об отказе не показывается",
    strict=False,
)
def test_declined_card_shows_error():
    """При оплате отклонённой картой должно появиться уведомление об отказе."""
    driver, wait = open_card_form()
    try:
        fill_card_form(driver, wait, DECLINED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        error_msg = bank_wait.until(EC.visibility_of_element_located(ERROR_NOTIFICATION))

        assert error_msg.is_displayed(), "Уведомление об ошибке не стало видимым"
        assert "отказал" in error_msg.text, (
            f"Текст уведомления не содержит 'отказал': {error_msg.text!r}"
        )
        print(f"\nУведомление об ошибке найдено: {error_msg.text!r}")
    except TimeoutException:
        _dump_evidence(driver, "issue1_no_error_notification")
        raise
    finally:
        driver.quit()


def test_declined_card_does_not_show_success():
    """Баг-репродукция (issue #1): UI не должен показывать «Успешно»
    при оплате отклонённой картой."""
    driver, wait = open_card_form()
    try:
        fill_card_form(driver, wait, DECLINED_CARD)

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        try:
            success_msg = bank_wait.until(
                EC.visibility_of_element_located(SUCCESS_NOTIFICATION)
            )
        except TimeoutException:
            print("\n«Успешно» не появилось — баг не воспроизвёлся (или уже исправлен)")
            return

        # Доказательства: скриншот, разметка пойманного элемента,
        # полный текст уведомления-обёртки
        os.makedirs("screenshots", exist_ok=True)
        driver.save_screenshot("screenshots/issue1_success_on_declined.png")

        print("\n=== БАГ-ДОКАЗАТЕЛЬСТВА ===")
        print("Пойманный элемент:")
        print("  tag:", success_msg.tag_name)
        print("  class:", success_msg.get_attribute("class"))
        print("  text:", repr(success_msg.text))
        print("  outerHTML (первые 500 символов):")
        print((success_msg.get_attribute("outerHTML") or "")[:500])

        # Ищем видимую обёртку уведомления — у неё должен быть полный текст
        containers = [
            el for el in driver.find_elements(By.CSS_SELECTOR, "[class*='notification']")
            if el.is_displayed() and (el.text or "").strip()
        ]
        for el in containers:
            print(f"\nВидимое уведомление: class={el.get_attribute('class')!r}, "
                  f"text={el.text!r}")

        full_text = " | ".join(el.text for el in containers) or success_msg.text
        assert False, (
            f"БАГ ПОДТВЕРЖДЁН: UI показал уведомление успешной операции "
            f"(текст: {full_text!r}) при оплате отклонённой картой. "
            f"См. issue #1, скриншот: screenshots/issue1_success_on_declined.png"
        )
    finally:
        driver.quit()


def test_declined_card_db_state(run_sql):
    """Блок 3.8: после оплаты отклонённой картой новая запись в payment_entity
    имеет статус DECLINED (не APPROVED). Проверка срезом «до/после» отправки —
    не зависит от истории БД."""
    driver, wait = open_card_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM payment_entity ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_card_form(driver, wait, DECLINED_CARD)

        DB_SETTLE_TIMEOUT = 15
        deadline = time.monotonic() + DB_SETTLE_TIMEOUT
        new_rows = []
        while time.monotonic() < deadline:
            new_rows = _parse_rows(run_sql(
                f"SELECT id, status, created FROM payment_entity "
                f"WHERE created > '{before_created}';"
            ))
            if new_rows:
                break
            time.sleep(1)

        assert new_rows, "Новая запись в payment_entity не появилась"
        statuses = {r["status"] for r in new_rows}
        assert statuses == {"DECLINED"}, (
            f"Ожидали только DECLINED для отклонённой операции, "
            f"получили {statuses}: {new_rows}. См. issue #1"
        )
        print(f"\n[3.8] OK: отклонённая операция сохранена со статусом DECLINED "
              f"(id={new_rows[0]['id']})")
    finally:
        driver.quit()