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
APPROVED_CARD = "4444 4444 4444 4441"
UNKNOWN_CARD = "1234 5678 9012 3456"

BUY_BUTTON = (By.XPATH, "//*[normalize-space(text())='Купить']")
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


def open_payment_form():
    """Открывает браузер и форму оплаты, возвращает (driver, wait)."""
    options = Options()
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    driver.get(BASE_URL)
    wait = WebDriverWait(driver, 15)

    wait.until(EC.element_to_be_clickable(BUY_BUTTON)).click()
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


def fill_form(driver, wait, card=None, month=None, year=None,
              owner=None, cvc=None):
    """Заполняет только переданные поля формы и нажимает «Продолжить».

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


def _wait_for_new_payment(run_sql, before_created, timeout=DB_SETTLE_TIMEOUT):
    """Ищет записи payment_entity, созданные ПОСЛЕ отправки формы.

    Возвращает список найденных записей (может быть пустым — это значит,
    что операция не зарегистрирована шлюзом).
    """
    deadline = time.monotonic() + timeout
    rows = []
    while time.monotonic() < deadline:
        rows = _parse_rows(run_sql(
            f"SELECT id, status, created FROM payment_entity "
            f"WHERE created > '{before_created}';"
        ))
        if rows:
            return rows
        time.sleep(1)
    return []


def test_3_2_empty_form_blocked(run_sql):
    """3.2: пустая форма → ошибки под полями, заявка в банк не уходит
    (в payment_entity не появляется новых записей)."""
    driver, wait = open_payment_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM payment_entity ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_form(driver, wait)  # ничего не заполняем

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".input_invalid")))
        errors = _visible_validation_errors(driver)
        assert errors, "Ошибок валидации не показано для пустой формы"
        assert len(errors) >= 4, (
            f"Ожидали ошибки минимум под 4 полями, показали: {errors}"
        )

        time.sleep(3)
        after = _wait_for_new_payment(run_sql, before_created, timeout=5)
        assert not after, (
            f"Пустая форма отправила заявку в банк: {after} — "
            f"валидация не заблокировала отправку"
        )
        print(f"\n[3.2] OK: пустая форма заблокирована, ошибки: {errors}")
    finally:
        driver.quit()


def test_3_3_unknown_card_rejected(run_sql):
    """3.3: незнакомая карта 1234 5678 9012 3456 → уведомление об отказе.
    Записи в payment_entity после отправки либо нет (операция шлюзом
    не регистрируется), либо она имеет статус DECLINED."""
    driver, wait = open_payment_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM payment_entity ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_form(driver, wait,
                  card=UNKNOWN_CARD, month="12", year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        error_msg = bank_wait.until(
            EC.visibility_of_element_located(ERROR_NOTIFICATION))
        assert "отказал" in error_msg.text, (
            f"Текст уведомления не содержит 'отказал': {error_msg.text!r}"
        )
        print(f"\nУведомление об отказе: {error_msg.text!r}")

        new_rows = _wait_for_new_payment(run_sql, before_created)

        if not new_rows:
            print("\n[3.3] DB: запись в payment_entity не создана — "
                  "операция по незнакомой карте шлюзом не регистрируется")
            return

        statuses = {r["status"] for r in new_rows}
        assert statuses == {"DECLINED"}, (
            f"Ожидали только DECLINED, получили {statuses}: {new_rows}"
        )
        print(f"\n[3.3] DB OK: создана запись со статусом DECLINED "
              f"(id={new_rows[0]['id']})")
    finally:
        driver.quit()


@pytest.mark.parametrize("bad_month", ["13", "00"])
def test_3_4_invalid_month(bad_month):
    """3.4: месяц 13 или 00 → ошибка валидации, отправка блокируется."""
    driver, wait = open_payment_form()
    try:
        fill_form(driver, wait,
                  card=APPROVED_CARD, month=bad_month, year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".input_invalid")))
        errors = _visible_validation_errors(driver)
        assert errors, f"Ошибок валидации не показано для месяца {bad_month}"
        print(f"\n[3.4] OK: месяц {bad_month} отклонён: {errors}")
    finally:
        driver.quit()


def test_3_6_far_future_year():
    """3.6: год 99 → ошибка валидации, отправка блокируется."""
    driver, wait = open_payment_form()
    try:
        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="99",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".input_invalid")))
        errors = _visible_validation_errors(driver)
        assert errors, "Ошибок валидации не показано для года 99"
        print(f"\n[3.6] OK: год 99 отклонён: {errors}")
    finally:
        driver.quit()


@pytest.mark.parametrize("cvc", ["1", "99", "00", "000"])
def test_3_7_cvc_validation(cvc):
    """3.7: валидация CVC.

    Короткие значения (1–2 цифры) отклоняются ошибкой «Неверный формат».
    CVC '000' формально проходит проверку длины и принимается формой —
    это баг, см. issue #3: тест намеренно оставлен красным как репродукция.
    """
    driver, wait = open_payment_form()
    try:
        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc=cvc)

        has_error = bool(driver.find_elements(By.CSS_SELECTOR, ".input_invalid"))
        errors = _visible_validation_errors(driver)

        if cvc == "000":
            assert has_error, (
                f"БАГ ПОДТВЕРЖДЁН (issue #3): CVC {cvc!r} принят валидацией — "
                f"подполевых ошибок нет ({errors or 'нет сообщений'}), "
                f"форма отправится в шлюз с недопустимым значением CVC"
            )
            print(f"\n[3.7] OK: CVC {cvc!r} отклонён — баг #3 не воспроизвёлся")
        else:
            assert has_error, f"CVC {cvc!r} не отклонён валидацией"
            print(f"\n[3.7] OK: CVC {cvc!r} отклонён: {errors}")
    finally:
        driver.quit()


@pytest.mark.parametrize("bad_owner, label", [
    ("123456", "цифры"),
    ("Иванов Иван", "кириллица"),
    ("!@#$%^&", "спецсимволы"),
])
def test_3_8_owner_validation(run_sql, bad_owner, label):
    """3.8: валидация поля «Владелец».

    Поле должно принимать только имя и фамилию латиницей. Недопустимые
    значения (цифры, кириллица, спецсимволы) должны отклоняться ошибкой
    валидации. Все три класса значений проходят без ошибок и уходят
    в шлюз — это баг, см. issue #4: тест намеренно оставлен красным
    как репродукция.
    """
    driver, wait = open_payment_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM payment_entity ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="26",
                  owner=bad_owner, cvc="999")

        has_error = bool(driver.find_elements(By.CSS_SELECTOR, ".input_invalid"))
        errors = _visible_validation_errors(driver)

        if has_error:
            print(f"\n[3.8] OK: владелец {label!r} отклонён: {errors} — "
                  f"issue #4 не воспроизвёлся")
            return

        # Ошибки нет — проверяем, дошёл ли баг до конца (успешная операция)
        deadline = time.monotonic() + BANK_TIMEOUT
        success_shown = False
        while time.monotonic() < deadline:
            if driver.find_elements(By.XPATH, "//*[contains(text(), 'Успешно')]"):
                success_shown = True
                break
            time.sleep(1)

        if success_shown:
            new_rows = _wait_for_new_payment(run_sql, before_created)
            db_note = (f"запись в payment_entity создана (status="
                       f"{new_rows[0]['status']})" if new_rows
                       else "запись в payment_entity не создана")

            os.makedirs("screenshots", exist_ok=True)
            driver.save_screenshot(
                f"screenshots/issue4_owner_{label}_success.png")

            assert False, (
                f"БАГ ПОДТВЕРЖДЁН (issue #4): владелец {label!r} "
                f"({bad_owner!r}) принят валидацией — подполевых ошибок нет "
                f"({errors or 'нет сообщений'}), показано «Успешно», "
                f"{db_note}. Скриншот: "
                f"screenshots/issue4_owner_{label}_success.png"
            )
        else:
            assert False, (
                f"БАГ ПОДТВЕРЖДЁН (issue #4): владелец {label!r} "
                f"({bad_owner!r}) принят валидацией — подполевых ошибок нет "
                f"({errors or 'нет сообщений'}), форма отправлена в шлюз, "
                f"ответ за {BANK_TIMEOUT} с не получен (банк может "
                f"отклонить операцию, но обратной связи пользователю нет)"
            )
    finally:
        driver.quit()


def test_6_2_single_record_per_submit(run_sql):
    """6.2: одно нажатие «Продолжить» → ровно одна запись в payment_entity
    (нет дублей)."""
    driver, wait = open_payment_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT id, created FROM payment_entity ORDER BY created DESC LIMIT 1;"
        ))
        before_created = before[0]["created"] if before else ""

        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))

        new_rows = _wait_for_new_payment(run_sql, before_created)
        assert new_rows, "Новая запись в payment_entity не появилась"
        time.sleep(3)  # даём шанс появиться дублям

        new_rows_after = _parse_rows(run_sql(
            f"SELECT id, status, created FROM payment_entity "
            f"WHERE created > '{before_created}';"
        ))
        assert len(new_rows_after) == 1, (
            f"Дубль записи: на одну отправку формы создано "
            f"{len(new_rows_after)} записей: {new_rows_after}"
        )
        assert new_rows_after[0]["status"] == "APPROVED", (
            f"Ожидали APPROVED, получили {new_rows_after[0]['status']!r}"
        )
        print(f"\n[6.2] OK: ровно одна запись APPROVED "
              f"(id={new_rows_after[0]['id']})")
    finally:
        driver.quit()
