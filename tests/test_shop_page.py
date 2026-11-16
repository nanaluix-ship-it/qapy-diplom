import requests
import allure

BASE_URL = "http://localhost:8080"


@allure.feature("Главная страница")
@allure.story("Доступность страницы магазина")
@allure.severity(allure.severity_level.CRITICAL)
def test_1_1_shop_page_is_available():
    """Главная страница отвечает со статусом 200."""
    response = requests.get(BASE_URL)
    assert response.status_code == 200


@allure.feature("Главная страница")
@allure.story("Корректность заголовка страницы")
@allure.severity(allure.severity_level.MINOR)
def test_1_2_shop_page_title_is_correct():
    """Заголовок страницы — «AQA: Заявка на карту»."""
    response = requests.get(BASE_URL)
    response.encoding = "utf-8"
    assert response.status_code == 200
    assert "AQA: Заявка на карту" in response.text
