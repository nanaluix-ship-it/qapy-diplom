import requests

APP = "http://localhost:8080"
GATE = "http://localhost:9999"

card_ok = {"number": "4444 4444 4444 4441", "year": "26", "month": "12",
           "card-holder": "IVAN IVANOV", "cvc": "999"}
card_bad = {"number": "4444 4444 4444 4442", "year": "26", "month": "12",
            "card-holder": "IVAN IVANOV", "cvc": "999"}
card_unknown = {"number": "1234 5678 9012 3456", "year": "26", "month": "12",
                "card-holder": "IVAN IVANOV", "cvc": "999"}

# 1. Поведение /api/v1/credit на 8080: валидное тело, невалидное, GET
for name, body in [("valid", card_ok), ("invalid", {"foo": "bar"})]:
    r = requests.post(APP + "/api/v1/credit", json=body, timeout=30)
    print(f"8080/api/v1/credit POST {name} -> {r.status_code}: {r.text[:300]!r}")
r = requests.get(APP + "/api/v1/credit", timeout=30)
print(f"8080/api/v1/credit GET -> {r.status_code}: {r.text[:300]!r}")

# 2. Соседние пути на 8080 — есть ли ещё "живые" API-эндпоинты
for path in ["/api/v1/pay", "/api/v1/payment", "/api/v1/approve", "/api/v1/credit/approve"]:
    r = requests.post(APP + path, json=card_ok, timeout=30)
    print(f"8080{path} -> {r.status_code}: {r.text[:200]!r}")

# 3. Заглушка: DECLINED и незнакомая карта
for path, body in [
    ("/payment", card_bad), ("/payment", card_unknown),
    ("/credit", card_bad), ("/credit", card_unknown),
]:
    r = requests.post(GATE + path, json=body, timeout=30)
    print(f"9999{path} -> {r.status_code}: {r.text[:200]!r}")
