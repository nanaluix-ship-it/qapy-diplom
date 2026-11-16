import requests

APP = "http://localhost:8080"
GATE = "http://localhost:9999"

# Тело, которое посылает фронтенд (проверим по документации курса)
card = {"number": "4444 4444 4444 4441", "year": "26", "month": "12",
        "card-holder": "IVAN IVANOV", "cvc": "999"}

for path in ["/api/v1/payment", "/api/v1/credit"]:
    try:
        r = requests.post(APP + path, json=card, timeout=30)
        print(f"{APP}{path} -> {r.status_code}: {r.text[:200]!r}")
    except Exception as e:
        print(f"{APP}{path} -> ошибка: {e}")

for path in ["/payment", "/credit"]:
    try:
        r = requests.post(GATE + path, json=card, timeout=30)
        print(f"{GATE}{path} -> {r.status_code}: {r.text[:200]!r}")
    except Exception as e:
        print(f"{GATE}{path} -> ошибка: {e}")
