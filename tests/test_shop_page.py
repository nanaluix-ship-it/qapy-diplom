import requests

BASE_URL = "http://localhost:8080"


def test_shop_page_is_available():
    """Главная страница отвечает со статусом 200."""
    response = requests.get(BASE_URL)
    assert response.status_code == 200


def test_shop_page_title_is_correct():
    """Заголовок страницы — «AQA: Заявка на карту»."""
    response = requests.get(BASE_URL)
    response.encoding = "utf-8"
    assert response.status_code == 200
    assert "AQA: Заявка на карту" in response.text
