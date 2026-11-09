# Дипломный проект по профессии «Тестировщик»

Дипломный проект — автоматизация тестирования комплексного сервиса, взаимодействующего с СУБД и API платежной системы.
## Запуск окружения

1. Поднять контейнеры:
   docker-compose up -d 
2. Дождаться статуса `healthy` у сервиса mysql.
3. Запустить приложение:
   java "-Dspring.datasource.url=jdbc:mysql://localhost:3307/app" 
   "-Dspring.datasource.username=app" "-Dspring.datasource.password=pass" -jar aqa-shop.jar
4. Открыть http://localhost:8080/ — страница «Путешествие дня».

Порты: MySQL — 3307 (порт 3306 занят локальной установкой), эмулятор банка — 9999.