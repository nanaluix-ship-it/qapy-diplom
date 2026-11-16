# Дипломный проект по профессии «Тестировщик»

Дипломный проект — автоматизация тестирования комплексного сервиса, взаимодействующего с СУБД и API платежной системы.

## Запуск окружения

1. Поднять контейнеры:
   ```powershell
   docker-compose up -d
   ```
2. Дождаться статуса `healthy` у сервиса mysql:
   ```powershell
   docker ps
   ```
3. Запустить приложение:
   ```powershell
   java "-Dspring.datasource.url=jdbc:mysql://localhost:3307/app" `
     "-Dspring.datasource.username=app" `
     "-Dspring.datasource.password=pass" `
     -jar aqa-shop.jar
   ```
4. Открыть http://localhost:8080/ — страница «Путешествие дня».

Порты: MySQL — 3307 (порт 3306 занят локальной установкой), эмулятор банка — 9999 (заглушка, поднимается вместе с контейнерами; отдельный запуск не требуется).

## Запуск автотестов

Предварительные требования: Python 3.10+, Google Chrome (тесты запускают Chrome в headless-режиме — окно браузера не нужно).
План тестирования с описанием тестов и их результатами в файле 'qa_checklist_diploma.md'
1. Установка зависимостей (один раз):
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Полный прогон с чистым отчётом Allure (35 тестов, ~15–20 минут):
   ```powershell
   Remove-Item allure-results -Recurse -Force
   pytest tests -v --alluredir=allure-results
   ```
3. Точечный запуск:
   ```powershell
   pytest tests/test_payment_negative.py -v
   pytest tests -k "3_7" -v
   ```
4. Просмотр отчёта Allure:
   ```powershell
   allure generate allure-results -o allure-report --clean
   allure open allure-report
   ```
   (Нужен установленный Allure Commandline; без него сводка — в выводе pytest в терминале.)

Важно: не запускать тесты параллельно (`-n` не использовать) — тесты зависят от состояния БД, параллельная отправка форм исказит срезы «до/после».

## Тестовые карты (шлюз-заглушка)

| Карта | Статус | Сценарий |
|---|---|---|
| `4444 4444 4444 4441` | APPROVED | Успешная оплата |
| `4444 4444 4444 4442` | DECLINED | Отказ банка |
| `1234 5678 9012 3456` | — | Незнакомая карта: операция не регистрируется шлюзом |

Любые остальные номера дают отказ, но **без** записи в БД — отличие задокументировано в чек-листе (3.3).

## Полезные команды

```powershell
# Последние платежи в БД
docker exec -it $(docker ps --filter "ancestor=mysql:8.0" -q | Select-Object -First 1) mysql -u app -ppass app -e "SELECT id, status, created FROM payment_entity ORDER BY created DESC LIMIT 5;"

# Последние кредитные заявки
docker exec -it $(docker ps --filter "ancestor=mysql:8.0" -q | Select-Object -First 1) mysql -u app -ppass app -e "SELECT id, status, created FROM credit_request_entity ORDER BY created DESC LIMIT 5;"

# Остановить инфраструктуру (данные БД в docker volume сохраняются)
docker-compose down
```
