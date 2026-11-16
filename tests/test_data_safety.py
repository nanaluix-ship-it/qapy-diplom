import allure
import pytest
from tests.conftest import attach_screenshot
from tests.test_payment_negative import (
    _parse_rows, _wait_for_new_payment,
    open_payment_form, fill_form, fake,
    APPROVED_CARD, BANK_TIMEOUT,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

SUCCESS_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'Успешно')]")

CARD_WITH_SPACES = "4444 4444 4444 4441"
CARD_DIGITS = "4444444444444441"

BUY_CREDIT_BUTTON = (By.XPATH, "//*[normalize-space(text())='Купить в кредит']")


def open_credit_form():
    """Открывает кредитную форму (тот же паттерн, что и open_payment_form).
    Если в test_credit_negative.py есть свой хелпер — используй его."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    driver.get("http://localhost:8080")
    wait = WebDriverWait(driver, 15)
    wait.until(EC.element_to_be_clickable(BUY_CREDIT_BUTTON)).click()
    return driver, wait


def _blob_from_tables(run_sql, before_created, tables):
    """Собирает все значения всех колонок записей всех таблиц,
    созданных после before_created, в одну строку для поиска."""
    parts = []
    for table in tables:
        rows = _parse_rows(run_sql(
            f"SELECT * FROM {table} WHERE created > '{before_created}';"
        ))
        for row in rows:
            parts.extend(str(v) for v in row.values())
    return "\n".join(parts)


@allure.feature("Безопасность данных")
@allure.story("Номер карты не сохраняется в БД — дебет")
@allure.severity(allure.severity_level.CRITICAL)
def test_7_1_card_number_not_stored_debit(run_sql):
    """7.1: после успешной оплаты номер карты нигде не сохраняется
    в открытом виде (требование задания)."""
    driver, wait = open_payment_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT MAX(created) AS max_created FROM ("
            "SELECT created FROM payment_entity "
            "UNION ALL SELECT created FROM order_entity) t;"
        ))
        before_created = (before[0]["max_created"]
                          if before and before[0]["max_created"] else "")

        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))

        assert _wait_for_new_payment(run_sql, before_created), (
            "Платёж не зафиксирован в БД — проверка безопасности данных "
            "в этом прогоне неинформативна"
        )

        blob = _blob_from_tables(run_sql, before_created,
                                 ["payment_entity", "order_entity"])
        assert CARD_DIGITS not in blob and CARD_WITH_SPACES not in blob, (
            "БАГ ПОДТВЕРЖДЁН (issue #5): номер карты найден в БД "
            "в открытом виде. Пробелы/без пробелов проверены по всем "
            "колонкам payment_entity и order_entity. "
            "Это серьёзное нарушение безопасности платёжных данных."
        )
        print("\n[7.1] OK: номер карты в БД не найден "
              "(в открытом виде не сохраняется)")
    finally:
        driver.quit()


@allure.feature("Безопасность данных")
@allure.story("Номер карты не сохраняется в БД — кредит")
@allure.severity(allure.severity_level.CRITICAL)
def test_7_2_card_number_not_stored_credit(run_sql):
    """7.2: то же требование для кредитного сценария."""
    driver, wait = open_credit_form()
    try:
        before = _parse_rows(run_sql(
            "SELECT MAX(created) AS max_created FROM ("
            "SELECT created FROM payment_entity "
            "UNION ALL SELECT created FROM credit_request_entity "
            "UNION ALL SELECT created FROM order_entity) t;"
        ))
        before_created = (before[0]["max_created"]
                          if before and before[0]["max_created"] else "")

        fill_form(driver, wait,
                  card=APPROVED_CARD, month="12", year="26",
                  owner=fake.first_name() + " " + fake.last_name(), cvc="999")

        bank_wait = WebDriverWait(driver, BANK_TIMEOUT)
        bank_wait.until(EC.visibility_of_element_located(SUCCESS_NOTIFICATION))

        blob = _blob_from_tables(run_sql, before_created,
                                 ["credit_request_entity", "order_entity"])
        assert CARD_DIGITS not in blob and CARD_WITH_SPACES not in blob, (
            "БАГ ПОДТВЕРЖДЁН (issue #5, кредит): номер карты найден "
            "в БД в открытом виде"
        )
        print("\n[7.2] OK: номер карты в кредитной ветке БД не найден")
    finally:
        driver.quit()
