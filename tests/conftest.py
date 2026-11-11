
import subprocess

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from faker import Faker

fake = Faker(locale="ru_RU")

BASE_URL = "http://localhost:8080"
APPROVED_CARD = "4444 4444 4444 4441"
DECLINED_CARD = "4444 4444 4444 4442"

BUY_BUTTON = (By.XPATH, "//*[normalize-space(text())='Купить']")
BUY_CREDIT_BUTTON = (By.XPATH, "//*[normalize-space(text())='Купить в кредит']")
CONTINUE_BUTTON = (
    By.XPATH,
    "//button[contains(., 'Продолжить')] | //*[contains(text(), 'Продолжить')]"
)
CARD_INPUT = (By.CSS_SELECTOR, "input[placeholder='0000 0000 0000 0000']")
SUCCESS_NOTIFICATION = (By.XPATH, "//*[contains(text(), 'Успешно')]")

BANK_TIMEOUT = 45


def make_driver():
    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    return driver


def open_payment_form(driver, wait):
    """Кнопка «Купить» → форма оплаты по карте."""
    wait.until(EC.element_to_be_clickable(BUY_BUTTON)).click()


def open_credit_form(driver, wait):
    """Кнопка «Купить в кредит» → форма кредита."""
    wait.until(EC.element_to_be_clickable(BUY_CREDIT_BUTTON)).click()


def fill_card_form(driver, wait, card_number,
                   month="12", year="26", cvc="999"):
    """Заполняет форму и нажимает «Продолжить»."""
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
    month_field.send_keys(month)
    year_field.clear()
    year_field.send_keys(year)
    holder_field.clear()
    holder_field.send_keys(fake.first_name() + " " + fake.last_name())
    cvc_field.clear()
    cvc_field.send_keys(cvc)

    wait.until(EC.element_to_be_clickable(CONTINUE_BUTTON)).click()


@pytest.fixture(scope="session")
def run_sql():
    """Выполняет SQL-запрос к MySQL в Docker, возвращает stdout."""
    def _run(query: str) -> str:
        result = subprocess.run(
            ["docker", "ps", "--filter", "ancestor=mysql:8.0", "-q"],
            capture_output=True, text=True, check=True,
        )
        container_id = result.stdout.strip().splitlines()[0]
        # Важно: без -it, из subprocess псевдотерминал недоступен
        proc = subprocess.run(
            ["docker", "exec", container_id,
             "mysql", "-u", "app", "-ppass", "app", "-e", query],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"SQL-ошибка: {proc.stderr}")
        return proc.stdout
    return _run
